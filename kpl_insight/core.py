"""
KPL official intelligence platform core.

This module centralizes schedule discovery, snapshot parsing, feature building,
replay loading, event detection and model inference so the dashboard and live
scripts do not drift apart.
"""

from __future__ import annotations

import ast
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import requests


from kpl_insight.paths import PROJECT_ROOT
MODEL_DIR = PROJECT_ROOT / "output" / "models"
REALTIME_DIR = PROJECT_ROOT / "data" / "realtime"
RAW_DIR = REALTIME_DIR / "raw_snapshots"
PREDICTION_DIR = REALTIME_DIR / "predictions"
DATASETS_DIR = REALTIME_DIR / "datasets"
CLEAN_DIR = DATASETS_DIR / "clean"
QUARANTINE_DIR = DATASETS_DIR / "quarantine"
MONITOR_STATUS_FILE = REALTIME_DIR / "monitor_status.json"
SCHEDULE_ARCHIVE_PATH = REALTIME_DIR / "schedule_archive.csv"
KPL_KNOWLEDGE_PATH = Path(__file__).resolve().parent / "resources" / "knowledge.json"
RAW_FALLBACK_DIR = PROJECT_ROOT / "data" / "raw"

BASE_URL_BATTLE = "https://prod.comp.smoba.qq.com/leaguesite/battle/open"
BASE_URL_LEAGUES = "https://prod.comp.smoba.qq.com/leaguesite/leagues/open"
BASE_URL_LEAGUE = "https://prod.comp.smoba.qq.com/leaguesite/matches/open"
BASE_URL_MATCH = "https://prod.comp.smoba.qq.com/leaguesite/match/battles/open"
LEAGUE_ID = 20260004  # 2026 KPL年度总决赛（进行中）；夏季赛=20260003，挑战者杯=20260002

HEADERS_API = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N)",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://pvp.qq.com/",
    "Origin": "https://pvp.qq.com",
}

POSITIONS = {2: "mid", 4: "support", 5: "jungle", 6: "top", 7: "adc"}
POSITION_CN = {
    "mid": "中路",
    "support": "游走",
    "jungle": "打野",
    "top": "对抗路",
    "adc": "发育路",
}
# battle_player_list 对位矩阵行序：对抗 / 打野 / 中路 / 发育 / 游走
PLAYER_LANE_ORDER = [6, 5, 2, 7, 4]
PLAYER_EQUIP_SLOTS = 6
RUNE_DICT_PATH = PROJECT_ROOT / "data" / "meta" / "rune_dict.json"

# bp_list.position（与 battle_player_list.position 编码不同）
BP_POSITION_CN = {
    0: "对抗路",
    1: "打野",
    2: "中路",
    3: "发育路",
    4: "游走",
}
BP_LANE_ORDER = [0, 1, 2, 3, 4]
BP_EXPECTED_STEPS = 20
BP_SMALL_SAMPLE_N = 20
# 终局常见结构：一 ban×4 → 一 pick×6 → 二 ban×6 → 二 pick×4
BP_PHASE_THRESHOLDS = ((4, "一 ban"), (10, "一 pick"), (16, "二 ban"), (20, "二 pick"))

STATUS_MAP = {0: "未开始", 1: "进行中", 2: "已结束"}
# Probe filter: keep replicas within this window of last accepted game_duration.
MONOTONIC_TOLERANCE_SEC = 30
# Accept filter: only tiny clock jitter; larger rewinds are stale API replicas.
REWIND_ACCEPT_TOLERANCE_SEC = 3


_KPL_SESSION: Any = None


def _kpl_session():
    """KPL 接口专用 Session：默认绕过系统 / 环境代理（国内接口直连，代理故障不影响采集）。

    需要走代理时设环境变量 ``KPL_USE_PROXY=1``。
    """
    global _KPL_SESSION
    if _KPL_SESSION is None:
        sess = requests.Session()
        sess.trust_env = os.environ.get("KPL_USE_PROXY", "").strip() == "1"
        sess.headers.update(HEADERS_API)
        _KPL_SESSION = sess
    return _KPL_SESSION


def api_get(url: str, params: dict[str, Any] | None = None, timeout: int = 12) -> dict[str, Any] | None:
    """Return a valid KPL API response, or None when the API is unavailable."""
    try:
        resp = _kpl_session().get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 200:
            return data
    except Exception:
        return None
    return None


def _register_legacy_loss_alias() -> None:
    """让 sklearn >=1.9 也能加载由 sklearn <=1.8 保存的模型产物。

    sklearn <=1.8 编译出的 Cython 损失类，其 ``__module__`` 被写成顶层名 ``_loss``，
    pickle 因此记下 ``_loss`` 作为模块名；到 sklearn >=1.9 这个顶层名已不存在，
    joblib.load 会抛 ``ModuleNotFoundError: No module named '_loss'``。
    这里把扩展模块的新位置登记成旧名，历史产物（V12 等）即可继续加载。
    只做模块别名登记，不改动任何模型参数，因此不影响已发布的评估口径。
    """
    if "_loss" in sys.modules:
        return
    try:
        from sklearn._loss import _loss as sklearn_loss  # sklearn >=1.9 的实际位置
    except Exception:
        return
    sys.modules["_loss"] = sklearn_loss


def load_model() -> dict[str, Any] | None:
    candidates = [
        MODEL_DIR / "v9_official_platform.joblib",
        # Optional local backup; model weights are not shipped with the source distribution.
        REALTIME_DIR / "model_backup" / "v9_official_platform.joblib",
        MODEL_DIR / "v8_realtime_enhanced.joblib",
        MODEL_DIR / "v7_realtime_stacking.joblib",
        MODEL_DIR / "v6_realtime_calibrated.joblib",
        MODEL_DIR / "v5_realtime_voting.joblib",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if not path:
        return None
    _register_legacy_loss_alias()
    return joblib.load(path)


def get_seconds(raw_duration: Any) -> int:
    value = raw_duration or 0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0
    return int(value / 1000 if value > 1000 else value)


def parse_start_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        ts = float(text)
        if ts > 10_000_000_000:
            ts /= 1000
        return datetime.fromtimestamp(ts)
    except (TypeError, ValueError, OSError):
        return None


def status_text(status: Any) -> str:
    try:
        return STATUS_MAP.get(int(status), str(status))
    except (TypeError, ValueError):
        return str(status or "未知")


def safe_literal(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value)
    if not text or text == "nan":
        return None
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None


def extract_team_name(value: Any) -> str:
    parsed = safe_literal(value)
    if isinstance(parsed, dict):
        return str(parsed.get("team_name") or parsed.get("team_abbreviation") or "")
    return str(value or "")


def extract_battle_ids(value: Any) -> list[str]:
    parsed = safe_literal(value)
    if not isinstance(parsed, list):
        return []
    battle_ids = []
    for item in parsed:
        if isinstance(item, dict) and item.get("battle_id"):
            battle_ids.append(str(item["battle_id"]))
    return battle_ids


def normalize_schedule_archive_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["league_id"] = df.get("league_id", "").astype(str)
    out["match_id"] = df.get("match_id", "").astype(str)
    out["start_time"] = df.get("start_time", "").astype(str)
    starts = pd.to_datetime(out["start_time"], errors="coerce")
    out["date"] = starts.dt.strftime("%Y-%m-%d").fillna("")
    out["year"] = starts.dt.year.fillna("").astype(str)
    out["team1"] = df.get("team1", df.get("camp1", "")).apply(extract_team_name)
    out["team2"] = df.get("team2", df.get("camp2", "")).apply(extract_team_name)
    out["status"] = df.get("status", "")
    out["status_text"] = out["status"].apply(status_text)
    out["stage"] = df.get("match_stage_desc", df.get("stage", df.get("match_stage_name", ""))).astype(str)
    out["round_name"] = df.get("match_stage_name", df.get("round_name", "")).astype(str)
    out["bo_type"] = df.get("bo", df.get("bo_type", "")).astype(str)
    battle_lists = df.get("match_battle_video_list", "").apply(extract_battle_ids)
    out["battle_ids"] = battle_lists.apply(lambda xs: "|".join(xs))
    out["battle_count"] = battle_lists.apply(len)
    out["cc_match_id"] = df.get("cc_match_id", "").astype(str)
    return out.fillna("")


@dataclass
class ScheduleMatch:
    match_id: str
    start_time: datetime | None
    team1: str
    team2: str
    status: int
    stage: str
    round_name: str
    bo_type: str
    raw: dict[str, Any]

    @property
    def status_text(self) -> str:
        return status_text(self.status)

    @property
    def display_name(self) -> str:
        date = self.start_time.strftime("%m-%d %H:%M") if self.start_time else "时间待定"
        return f"{date} · {self.team1} vs {self.team2} · {self.status_text}"


class ScheduleCenter:
    """Fetch league schedule and battle IDs from the official KPL API."""

    def __init__(self, league_id: int = LEAGUE_ID):
        self.league_id = league_id

    def fetch_matches(self) -> list[ScheduleMatch]:
        data = api_get(BASE_URL_LEAGUE, {"league_id": self.league_id})
        rows = data.get("results", []) if data else []
        return self.parse_match_rows(rows, self.league_id)

    @staticmethod
    def parse_match_rows(rows: list[dict[str, Any]], league_id: int | str) -> list[ScheduleMatch]:
        matches: list[ScheduleMatch] = []
        for row in rows:
            team1 = (
                row.get("camp1_team_name")
                or row.get("team1_name")
                or row.get("camp1", {}).get("team_name", "")
                or row.get("team_name_a", "")
            )
            team2 = (
                row.get("camp2_team_name")
                or row.get("team2_name")
                or row.get("camp2", {}).get("team_name", "")
                or row.get("team_name_b", "")
            )
            start = parse_start_time(row.get("start_time") or row.get("match_time") or row.get("time"))
            try:
                status = int(row.get("status", 0) or 0)
            except (TypeError, ValueError):
                status = 0
            match_id = str(row.get("match_id") or row.get("id") or "")
            if not match_id:
                continue
            stage = row.get("match_stage") or row.get("stage_name") or row.get("group_name") or "未知赛段"
            round_name = row.get("round_name") or row.get("match_round") or row.get("round") or "未知轮次"
            bo_type = row.get("bo") or row.get("bo_type") or row.get("match_type") or "BO?"
            matches.append(
                ScheduleMatch(
                    match_id=match_id,
                    start_time=start,
                    team1=team1 or "待定",
                    team2=team2 or "待定",
                    status=status,
                    stage=str(stage),
                    round_name=str(round_name),
                    bo_type=str(bo_type),
                    raw={**row, "league_id": str(row.get("league_id") or league_id)},
                )
            )
        return sorted(matches, key=lambda m: m.start_time or datetime.max)

    @staticmethod
    def candidate_league_ids(start_year: int = 2018, end_year: int | None = None, event_codes: range = range(1, 13)) -> list[int]:
        """Generate likely KPL league_id values: YYYY + 4-digit event code."""
        end_year = end_year or datetime.now().year
        return [int(f"{year}{code:04d}") for year in range(start_year, end_year + 1) for code in event_codes]

    def fetch_available_leagues(self) -> list[dict[str, Any]]:
        """Try the official league list endpoint. Fallback callers can use candidate ids."""
        data = api_get(BASE_URL_LEAGUES)
        rows = data.get("results", []) if data else []
        return rows if isinstance(rows, list) else []

    def fetch_matches_by_league_id(self, league_id: int | str) -> list[ScheduleMatch]:
        data = api_get(BASE_URL_LEAGUE, {"league_id": league_id})
        rows = data.get("results", []) if data else []
        return self.parse_match_rows(rows, league_id)

    def build_schedule_archive(
        self,
        league_ids: list[int | str] | None = None,
        start_year: int = 2018,
        end_year: int | None = None,
        event_codes: range = range(1, 13),
        sleep_sec: float = 0.15,
        save_path: Path = SCHEDULE_ARCHIVE_PATH,
    ) -> pd.DataFrame:
        """
        Crawl multi-season schedules and cache them.

        Notebook finding: league schedule is available from
        `/leaguesite/matches/open?league_id=...`; every row contains match_id,
        start_time, teams, status and match_battle_video_list with battle_id list.
        """
        if league_ids is None:
            api_leagues = self.fetch_available_leagues()
            league_ids = [
                x.get("league_id") or x.get("id")
                for x in api_leagues
                if str(x.get("league_id") or x.get("id") or "").isdigit()
            ]
            if not league_ids:
                league_ids = self.candidate_league_ids(start_year, end_year, event_codes)

        archive_rows: list[dict[str, Any]] = []
        seen = set()
        for lid in league_ids:
            matches = self.fetch_matches_by_league_id(lid)
            if not matches:
                continue
            for match in matches:
                key = (str(match.raw.get("league_id") or lid), str(match.match_id))
                if key in seen:
                    continue
                seen.add(key)
                battle_ids = extract_battle_ids(match.raw.get("match_battle_video_list"))
                archive_rows.append(
                    {
                        "league_id": str(match.raw.get("league_id") or lid),
                        "match_id": match.match_id,
                        "start_time": match.start_time.strftime("%Y-%m-%d %H:%M:%S") if match.start_time else "",
                        "date": match.start_time.strftime("%Y-%m-%d") if match.start_time else "",
                        "year": match.start_time.year if match.start_time else "",
                        "team1": match.team1,
                        "team2": match.team2,
                        "status": match.status,
                        "status_text": match.status_text,
                        "stage": match.stage,
                        "round_name": match.round_name,
                        "bo_type": match.bo_type,
                        "battle_ids": "|".join(battle_ids),
                        "battle_count": len(battle_ids),
                        "cc_match_id": match.raw.get("cc_match_id", ""),
                    }
                )
            time.sleep(sleep_sec)

        df = pd.DataFrame(archive_rows)
        if not df.empty:
            df = df.sort_values(["start_time", "match_id"]).reset_index(drop=True)
            # 跨赛季合并：保留既有归档中本次未刷新联赛的行（避免单联赛刷新覆盖其它赛季）
            if save_path.exists():
                try:
                    old = pd.read_csv(save_path, dtype={"league_id": str, "match_id": str}).fillna("")
                    fresh_leagues = set(df["league_id"].astype(str).unique())
                    keep = old[~old["league_id"].astype(str).isin(fresh_leagues)]
                    if not keep.empty:
                        df = pd.concat([keep, df], ignore_index=True)
                        df = df.drop_duplicates(subset=["league_id", "match_id"], keep="last")
                        df = df.sort_values(["start_time", "match_id"]).reset_index(drop=True)
                except (OSError, pd.errors.ParserError):
                    pass
            body = df.to_csv(index=False, lineterminator="\n")
            try:
                old_body = save_path.read_text(encoding="utf-8-sig")
                if old_body == body:
                    return df
            except OSError:
                pass
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(body, encoding="utf-8-sig")
        return df

    def load_schedule_archive(self, path: Path = SCHEDULE_ARCHIVE_PATH) -> pd.DataFrame:
        if path.exists():
            return pd.read_csv(path, dtype={"league_id": str, "match_id": str}).fillna("")
        processed = PROJECT_ROOT / "data" / "processed" / "schedule.csv"
        if processed.exists():
            df = pd.read_csv(processed, dtype={"league_id": str, "match_id": str}).fillna("")
            return normalize_schedule_archive_frame(df)
        return pd.DataFrame()

    def query_schedule_archive(
        self,
        date: str | None = None,
        team_keyword: str | None = None,
        stage_keyword: str | None = None,
        path: Path = SCHEDULE_ARCHIVE_PATH,
    ) -> pd.DataFrame:
        df = self.load_schedule_archive(path)
        if df.empty:
            return df
        out = df.copy()
        if date:
            out = out[out["date"].astype(str) == date]
        if team_keyword:
            kw = team_keyword.strip()
            out = out[out["team1"].astype(str).str.contains(kw, case=False, na=False) | out["team2"].astype(str).str.contains(kw, case=False, na=False)]
        if stage_keyword:
            kw = stage_keyword.strip()
            out = out[out["stage"].astype(str).str.contains(kw, case=False, na=False) | out["round_name"].astype(str).str.contains(kw, case=False, na=False)]
        return out.reset_index(drop=True)

    def match_ids_for_date(self, date: str | None = None) -> list[str]:
        date = date or datetime.now().strftime("%Y-%m-%d")
        df = self.query_schedule_archive(date=date)
        if df.empty:
            return [m.match_id for m in self.today_matches()]
        return df["match_id"].astype(str).drop_duplicates().tolist()

    def today_matches(self, now: datetime | None = None) -> list[ScheduleMatch]:
        now = now or datetime.now()
        return [m for m in self.fetch_matches() if m.start_time and m.start_time.date() == now.date()]

    def get_match_by_id(self, match_id: str) -> ScheduleMatch | None:
        for match in self.fetch_matches():
            if match.match_id == str(match_id):
                return match
        return None

    def resolve_monitor_match(
        self,
        explicit_match_id: str | None = None,
        date: str | None = None,
        fallback: bool = True,
    ) -> ScheduleMatch | None:
        """Pick the match that should be monitored right now.

        ``fallback=False`` 时严格只看 ``date`` 当天：当天没有就返回 None，
        不去 ``active_or_next_match()`` 跨日期兜底。

        为什么需要这个开关：``active_or_next_match()`` 的最后一步是 ``matches[-1]``，
        在没有进行中/即将开始的比赛时，它会返回列表里最后一场——**哪怕那场早就打完了**。
        跨天滚动必须严格按日期找，否则会绕开窗口限制选中过期或过远的比赛。
        """
        if explicit_match_id:
            return self.get_match_by_id(explicit_match_id)
        today = self.today_matches() if date is None else [
            m for m in self.fetch_matches()
            if m.start_time and m.start_time.strftime("%Y-%m-%d") == date
        ]
        if not today:
            return self.active_or_next_match() if fallback else None
        active = [m for m in today if m.status == 1]
        if active:
            return sorted(active, key=lambda m: m.start_time or datetime.max)[0]
        now = datetime.now()
        upcoming = [
            m for m in today
            if m.status == 0 and m.start_time and m.start_time >= now - timedelta(minutes=30)
        ]
        if upcoming:
            return sorted(upcoming, key=lambda m: m.start_time or datetime.max)[0]
        pending = [m for m in today if m.status != 2]
        return sorted(pending, key=lambda m: m.start_time or datetime.max)[0] if pending else None

    def resolve_monitor_match_rolling(
        self,
        preferred_date: str | None = None,
        max_days_ahead: int = 7,
    ) -> tuple[ScheduleMatch | None, str | None]:
        """跨天安全的选场：preferred_date 只是「起始偏好」，不是锁定值。

        2026-10-18 事故：monitor 以 ``--date 2026-10-17`` 启动后进程不重启，
        date 就永远钉死在 10-17；那天比赛全结束后 ``resolve_monitor_match`` 恒为 None，
        进程一直 waiting_schedule，20:00 那场整场没被采集（页面还显示「待开赛」）。

        所以这里按 偏好日 → 今天 → 未来 N 天 依次试，返回第一个真有活可干的日期。
        返回 ``(match, 实际选中的日期)``；都找不到则返回 ``(None, None)``。
        """
        today = datetime.now().date()
        candidates = []
        if preferred_date:
            candidates.append(preferred_date)
        candidates.append(today.strftime("%Y-%m-%d"))
        for i in range(1, max_days_ahead + 1):
            candidates.append((today + timedelta(days=i)).strftime("%Y-%m-%d"))

        seen: set[str] = set()
        for day in candidates:
            if day in seen:
                continue
            seen.add(day)
            # fallback=False：当天没有就说没有，交给下一个候选日期，
            # 否则会被 active_or_next_match 的 matches[-1] 兜底选中过期比赛。
            match = self.resolve_monitor_match(None, date=day, fallback=False)
            if match:
                return match, day
        return None, None

    def next_match_after(self, match_id: str, date: str | None = None) -> ScheduleMatch | None:
        """Return the next scheduled match on the same day after match_id."""
        today = self.today_matches() if date is None else [
            m for m in self.fetch_matches()
            if m.start_time and m.start_time.strftime("%Y-%m-%d") == date
        ]
        today = sorted(today, key=lambda m: m.start_time or datetime.max)
        found = False
        for match in today:
            if found:
                return match
            if match.match_id == str(match_id):
                found = True
        return None

    def active_or_next_match(self) -> ScheduleMatch | None:
        matches = self.fetch_matches()
        active = [m for m in matches if m.status == 1]
        if active:
            return active[0]
        now = datetime.now()
        upcoming = [m for m in matches if m.start_time and m.start_time >= now - timedelta(hours=1)]
        return upcoming[0] if upcoming else (matches[-1] if matches else None)

    def fetch_battles(self, match_id: str) -> list[dict[str, Any]]:
        data = api_get(BASE_URL_MATCH, {"match_id": match_id})
        return data.get("results", []) if data else []

    def fetch_active_battle_id(self, match_id: str) -> str | None:
        battles = self.fetch_battles(match_id)
        active = [b for b in battles if int(b.get("status", 0) or 0) == 1 and b.get("battle_id")]
        return str(active[-1]["battle_id"]) if active else None

    def fetch_current_battle_id(self, match_id: str) -> str | None:
        """Return active battle_id, or the latest battle_id for replay/backfill only."""
        active_id = self.fetch_active_battle_id(match_id)
        if active_id:
            return active_id
        battles = self.fetch_battles(match_id)
        if not battles:
            return None
        with_ids = [b for b in battles if b.get("battle_id")]
        return str(with_ids[-1]["battle_id"]) if with_ids else None

    def fetch_live_battle_id(self, match_id: str) -> str | None:
        """Only return a battle that is actively running (status=1)."""
        return self.fetch_active_battle_id(match_id)


def fetch_freshest_battle(
    battle_id: str,
    n_probes: int = 3,
    gap_sec: float = 0.6,
    parallel: bool = True,
    min_game_sec: int = 0,
) -> dict[str, Any] | None:
    """Probe replicas and return the battle response with max game_duration."""
    params = {"battle_id": battle_id}
    candidates: list[tuple[int, int, dict[str, Any]]] = []

    if parallel and n_probes > 1:
        with ThreadPoolExecutor(max_workers=n_probes) as pool:
            futures = [pool.submit(api_get, BASE_URL_BATTLE, params) for _ in range(n_probes)]
            for fut in as_completed(futures):
                data = fut.result()
                if data:
                    bd = data.get("data", {})
                    sec = get_seconds(bd.get("game_duration"))
                    gold = int((bd.get("camp1", {}) or {}).get("gold", 0) or 0) + int(
                        (bd.get("camp2", {}) or {}).get("gold", 0) or 0
                    )
                    candidates.append((sec, gold, data))
    else:
        for i in range(n_probes):
            data = api_get(BASE_URL_BATTLE, params)
            if data:
                bd = data.get("data", {})
                sec = get_seconds(bd.get("game_duration"))
                gold = int((bd.get("camp1", {}) or {}).get("gold", 0) or 0) + int(
                    (bd.get("camp2", {}) or {}).get("gold", 0) or 0
                )
                candidates.append((sec, gold, data))
            if i < n_probes - 1:
                time.sleep(gap_sec)

    if not candidates:
        return None
    if min_game_sec > 0:
        fresh = [c for c in candidates if c[0] + MONOTONIC_TOLERANCE_SEC >= min_game_sec]
        if fresh:
            candidates = fresh
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2]


def is_monotonic_snapshot(
    snap: dict[str, Any],
    history: list[dict[str, Any]] | None,
    tolerance_sec: int = REWIND_ACCEPT_TOLERANCE_SEC,
) -> bool:
    """Reject API replicas that roll game_duration backward beyond tiny jitter.

    Probe selection still uses MONOTONIC_TOLERANCE_SEC; acceptance is stricter so
    ~20–30s stale replicas (e.g. 60s after 84s) cannot overwrite predictions.
    """
    if int(snap.get("status", 0) or 0) == 2:
        return True
    if not history:
        return True
    cur_t = int(snap.get("time_sec", 0) or snap.get("snapshot_time_sec", 0) or 0)
    prev_t = int(history[-1].get("time_sec", 0) or history[-1].get("snapshot_time_sec", 0) or 0)
    if prev_t <= 0:
        return True
    return cur_t + tolerance_sec >= prev_t


def refresh_schedule_archive(league_id: int | None = None) -> int:
    """Refresh cached schedule_archive.csv from live API."""
    center = ScheduleCenter(league_id or LEAGUE_ID)
    archive = center.build_schedule_archive(league_ids=[league_id or LEAGUE_ID])
    return len(archive)


def compute_lag_sec(
    snap: dict[str, Any],
    anchor_wall: datetime | None,
    anchor_game_sec: int | None,
) -> float | None:
    """Wall-clock elapsed minus in-game elapsed since battle anchor."""
    if anchor_wall is None or anchor_game_sec is None:
        return None
    game_sec = int(snap.get("time_sec", 0) or snap.get("snapshot_time_sec", 0) or 0)
    if game_sec <= 0:
        return None
    wall_elapsed = (datetime.now() - anchor_wall).total_seconds()
    game_elapsed = game_sec - anchor_game_sec
    return round(wall_elapsed - game_elapsed, 1)


def sanitize_lag_sec(
    lag_sec: float | None,
    prev_lag_sec: float | None = None,
    *,
    abs_limit: float = 120.0,
    jump_limit: float = 60.0,
) -> tuple[float | None, bool]:
    """Clamp noisy lag; return (clean_lag_or_None, clock_jump_flag)."""
    if lag_sec is None:
        return None, False
    try:
        lag = float(lag_sec)
    except (TypeError, ValueError):
        return None, True
    if abs(lag) > abs_limit:
        return None, True
    if prev_lag_sec is not None:
        try:
            if abs(lag - float(prev_lag_sec)) > jump_limit:
                return None, True
        except (TypeError, ValueError):
            pass
    return round(lag, 1), False


def phase_of_minute(minute: float | int) -> str:
    m = float(minute)
    if m <= 8:
        return "early"
    if m <= 15:
        return "mid"
    return "late"


def expected_calibration_error(y_true: np.ndarray, prob: np.ndarray, n_bins: int = 10) -> float:
    """ECE with equal-width probability bins."""
    y = np.asarray(y_true, dtype=float)
    p = np.clip(np.asarray(prob, dtype=float), 0.0, 1.0)
    if len(y) == 0:
        return 0.0
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi if i < n_bins - 1 else p <= hi)
        if not np.any(mask):
            continue
        ece += (mask.sum() / len(p)) * abs(y[mask].mean() - p[mask].mean())
    return float(ece)


def evaluate_prediction_arrays(y_true: np.ndarray, prob: np.ndarray) -> dict[str, float]:
    """Shared metrics for train/backtest (AUC secondary; Brier/ECE primary)."""
    from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score

    y = np.asarray(y_true, dtype=int)
    p = np.clip(np.asarray(prob, dtype=float), 1e-6, 1 - 1e-6)
    if len(y) == 0:
        return {"n": 0, "auc": 0.5, "accuracy": 0.0, "brier": 0.0, "ece": 0.0, "direction_acc": 0.0}
    pred = (p >= 0.5).astype(int)
    direction = ((p > 0.5) & (y == 1)) | ((p < 0.5) & (y == 0)) | (np.isclose(p, 0.5))
    return {
        "n": int(len(y)),
        "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else 0.5,
        "accuracy": float(accuracy_score(y, pred)),
        "brier": float(brier_score_loss(y, p)),
        "ece": float(expected_calibration_error(y, p)),
        "direction_acc": float(np.mean(direction)),
    }


def evaluate_phase_metrics(minutes: np.ndarray, y_true: np.ndarray, prob: np.ndarray) -> dict[str, dict[str, float]]:
    minutes = np.asarray(minutes, dtype=float)
    y = np.asarray(y_true)
    p = np.asarray(prob)
    out: dict[str, dict[str, float]] = {"all": evaluate_prediction_arrays(y, p)}
    for phase in ("early", "mid", "late"):
        mask = np.array([phase_of_minute(m) == phase for m in minutes])
        out[phase] = evaluate_prediction_arrays(y[mask], p[mask])
    return out


def prediction_confidence(minute: float | int, prob: float, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    """Product-facing confidence badge for early / near-coin-flip predictions."""
    m = float(minute)
    p = float(prob)
    edge = abs(p - 0.5)
    low = m <= 5 or edge < 0.06
    reason = []
    if m <= 5:
        reason.append("开局信息不足")
    if edge < 0.06:
        reason.append("胜率接近 50%")
    return {
        "low_confidence": low,
        "confidence": "low" if low else ("medium" if m <= 8 or edge < 0.12 else "high"),
        "reason": "；".join(reason) if reason else "局势信号较充分",
        "use_time_shrinkage": bool((artifact or {}).get("use_time_shrinkage", False)),
    }


def adaptive_poll_interval(
    gold_diff_velocity: float,
    *,
    interval_calm: int = 3,
    interval_hot: int = 2,
    hot_velocity_threshold: float = 150.0,
) -> float:
    """Shorter polling during high-tempo moments (team fights / swings)."""
    if abs(gold_diff_velocity) >= hot_velocity_threshold:
        return max(0.05, float(interval_hot))
    return max(0.05, float(interval_calm))


PREDICTION_CSV_FIELDS = [
    "collected_at",
    "match_id",
    "battle_id",
    "minute",
    "snapshot_time_sec",
    "lag_sec",
    "camp1_team",
    "camp2_team",
    "camp1_win_prob",
    "camp2_win_prob",
    "gold_diff",
    "kill_diff",
    "tower_diff",
    "objective_value_score",
    "tempo_swing_score",
    "top_factor",
    "gold_guard_applied",
    # 模型归因：没有这两列，事后无法回答"这条直播预测是哪个模型给的"，
    # 重放 vs 直播的差异就永远分不清是"模型换了"还是"实时数据更脏"
    "model_version",
    "model_trained_at",
    "model_fp",
    "feature_hash",
    "predict_latency_ms",
    "prob_raw",
    "prob_model",
    "status",
    "win_camp",
]


def parse_snapshot(raw_data: dict[str, Any], battle_id: str = "") -> dict[str, Any]:
    game_sec = get_seconds(raw_data.get("game_duration"))
    c1 = raw_data.get("camp1", {}) or {}
    c2 = raw_data.get("camp2", {}) or {}
    snap: dict[str, Any] = {
        "battle_id": battle_id,
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "time_sec": int(game_sec),
        "snapshot_time_sec": int(game_sec),
        "minute": game_sec / 60,
        "minute_bin": max(int(game_sec / 60), 1),
        "camp1_team": c1.get("team_name", "Camp1"),
        "camp2_team": c2.get("team_name", "Camp2"),
        "camp1_gold": c1.get("gold", 0) or 0,
        "camp2_gold": c2.get("gold", 0) or 0,
        "camp1_kill": c1.get("kill_num", 0) or 0,
        "camp2_kill": c2.get("kill_num", 0) or 0,
        "camp1_assist": c1.get("assist_num", 0) or 0,
        "camp2_assist": c2.get("assist_num", 0) or 0,
        "camp1_death": c1.get("death_num", 0) or 0,
        "camp2_death": c2.get("death_num", 0) or 0,
        "camp1_tower": c1.get("push_tower_num", 0) or 0,
        "camp2_tower": c2.get("push_tower_num", 0) or 0,
        "camp1_tyrant": c1.get("kill_tyrant_num", 0) or 0,
        "camp2_tyrant": c2.get("kill_tyrant_num", 0) or 0,
        "camp1_dark_tyrant": c1.get("kill_dark_tyrant_num", 0) or 0,
        "camp2_dark_tyrant": c2.get("kill_dark_tyrant_num", 0) or 0,
        "camp1_lord": c1.get("kill_big_dragon_num", 0) or 0,
        "camp2_lord": c2.get("kill_big_dragon_num", 0) or 0,
        "camp1_prophet": c1.get("kill_prophet_dragon_num", 0) or 0,
        "camp2_prophet": c2.get("kill_prophet_dragon_num", 0) or 0,
        "camp1_shadow": c1.get("kill_shadow_dragon_num", 0) or 0,
        "camp2_shadow": c2.get("kill_shadow_dragon_num", 0) or 0,
        "camp1_storm": c1.get("kill_storm_dragon_king_num", 0) or 0,
        "camp2_storm": c2.get("kill_storm_dragon_king_num", 0) or 0,
        "status": raw_data.get("status", 0) or 0,
        "win_camp": raw_data.get("win_camp", 0) or 0,
    }
    players = raw_data.get("battle_player_list", []) or []
    snap["players"] = players
    for pos_id, pos_name in POSITIONS.items():
        c1_p = [p for p in players if p.get("camp") == 1 and p.get("position") == pos_id]
        c2_p = [p for p in players if p.get("camp") == 2 and p.get("position") == pos_id]
        snap[f"c1_gold_{pos_name}"] = sum(p.get("gold", 0) or 0 for p in c1_p)
        snap[f"c2_gold_{pos_name}"] = sum(p.get("gold", 0) or 0 for p in c2_p)
        snap[f"c1_hurt_{pos_name}"] = sum(p.get("hurt_to_hero_total", 0) or 0 for p in c1_p)
        snap[f"c2_hurt_{pos_name}"] = sum(p.get("hurt_to_hero_total", 0) or 0 for p in c2_p)
        snap[f"c1_behurt_{pos_name}"] = sum(p.get("be_hurt_by_hero_total", 0) or 0 for p in c1_p)
        snap[f"c2_behurt_{pos_name}"] = sum(p.get("be_hurt_by_hero_total", 0) or 0 for p in c2_p)
        snap[f"c1_kill_{pos_name}"] = sum(p.get("kill_num", 0) or 0 for p in c1_p)
        snap[f"c2_kill_{pos_name}"] = sum(p.get("kill_num", 0) or 0 for p in c2_p)
        snap[f"c1_death_{pos_name}"] = sum(p.get("death_num", 0) or 0 for p in c1_p)
        snap[f"c2_death_{pos_name}"] = sum(p.get("death_num", 0) or 0 for p in c2_p)
        snap[f"c1_assist_{pos_name}"] = sum(p.get("assist_num", 0) or 0 for p in c1_p)
        snap[f"c2_assist_{pos_name}"] = sum(p.get("assist_num", 0) or 0 for p in c2_p)
        snap[f"c1_level_{pos_name}"] = max([p.get("level", 0) or 0 for p in c1_p], default=0)
        snap[f"c2_level_{pos_name}"] = max([p.get("level", 0) or 0 for p in c2_p], default=0)
    return snap


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (default 95%)."""
    if n <= 0:
        return (0.0, 0.0)
    successes = max(0, min(int(successes), int(n)))
    n = int(n)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    lo = max(0.0, (centre - margin) / denom)
    hi = min(1.0, (centre + margin) / denom)
    return (lo, hi)


def filter_teams_window(teams: pd.DataFrame, mode: str = "all") -> pd.DataFrame:
    """Slice team-battle rows by window: ``all`` | ``last_7d`` (by ``date``)."""
    if teams is None or teams.empty:
        return pd.DataFrame() if teams is None else teams.copy()
    out = teams.copy()
    key = str(mode or "all").strip().lower()
    if key in {"all", "全部", ""}:
        return out
    if key not in {"last_7d", "7d", "近7天", "近 7 天"}:
        return out
    if "date" not in out.columns:
        return out.iloc[0:0].copy()
    dates = pd.to_datetime(out["date"], errors="coerce")
    cutoff = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=6)
    return out.loc[dates.notna() & (dates >= cutoff)].copy()


def build_proxy_standings(teams_df: pd.DataFrame) -> pd.DataFrame:
    """Proxy standings: wins → win_rate → avg_gold_diff; includes Wilson CI.

    Un-decided battles (missing winner → ``win`` 为空) are excluded.
    Not official league points — rank is estimated from window battle rows.
    """
    cols = [
        "rank",
        "team",
        "wins",
        "losses",
        "games",
        "win_rate",
        "wilson_lo",
        "wilson_hi",
        "avg_gold_diff",
        "avg_kill_diff",
        "avg_tower_diff",
        "net_gold",
    ]
    if teams_df is None or teams_df.empty or "team" not in teams_df.columns:
        return pd.DataFrame(columns=cols)

    df = teams_df.copy()
    df["win"] = pd.to_numeric(df.get("win", 0), errors="coerce")
    df = df[df["win"].notna()].copy()  # 未结算对局不计入积分榜
    df["win"] = df["win"].astype(int)
    for col in ("gold_diff", "kill_diff", "tower_diff"):
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    g = (
        df.groupby("team", as_index=False)
        .agg(
            games=("win", "count"),
            wins=("win", "sum"),
            avg_gold_diff=("gold_diff", "mean"),
            avg_kill_diff=("kill_diff", "mean"),
            avg_tower_diff=("tower_diff", "mean"),
            net_gold=("gold_diff", "sum"),
        )
    )
    g["losses"] = (g["games"] - g["wins"]).astype(int)
    g["wins"] = g["wins"].astype(int)
    g["games"] = g["games"].astype(int)
    g["win_rate"] = np.where(g["games"] > 0, g["wins"] / g["games"], 0.0)

    lo_hi = [wilson_ci(int(w), int(n)) for w, n in zip(g["wins"], g["games"])]
    g["wilson_lo"] = [x[0] for x in lo_hi]
    g["wilson_hi"] = [x[1] for x in lo_hi]

    g = g.sort_values(
        ["wins", "win_rate", "avg_gold_diff"],
        ascending=[False, False, False],
        kind="mergesort",
    ).reset_index(drop=True)
    g.insert(0, "rank", np.arange(1, len(g) + 1))
    return g[cols]


def team_style_radar(df: pd.DataFrame) -> dict[str, float]:
    """Five-axis style radar (0–1), same normalization as the legacy dashboard page."""
    empty = {"胜率": 0.0, "经济": 0.0, "团战": 0.0, "推进": 0.0, "资源": 0.0}
    if df is None or df.empty:
        return empty
    win = float(pd.to_numeric(df.get("win", 0), errors="coerce").fillna(0).mean())
    gold = float(pd.to_numeric(df.get("gold_diff", 0), errors="coerce").fillna(0).mean())
    kill = float(pd.to_numeric(df.get("kill_diff", 0), errors="coerce").fillna(0).mean())
    tower = float(pd.to_numeric(df.get("tower_diff", 0), errors="coerce").fillna(0).mean())
    if "objectives" in df.columns:
        obj = float(pd.to_numeric(df["objectives"], errors="coerce").fillna(0).mean())
    else:
        obj = 0.0
    return {
        "胜率": win,
        "经济": float(np.clip((gold + 8000) / 16000, 0, 1)),
        "团战": float(np.clip((kill + 10) / 20, 0, 1)),
        "推进": float(np.clip((tower + 6) / 12, 0, 1)),
        "资源": float(np.clip(obj / 6, 0, 1)),
    }


def _bp_phase_for_step(step: int, action: str) -> str:
    for upper, name in BP_PHASE_THRESHOLDS:
        if step < upper:
            return name
    return f"其他 {action}"


def _extract_battle_payload(raw_or_snap: Any) -> dict[str, Any]:
    """Normalize API envelope / data dict / snapshot-like dict to battle payload."""
    if raw_or_snap is None:
        return {}
    if isinstance(raw_or_snap, list):
        return {"bp_list": raw_or_snap}
    if not isinstance(raw_or_snap, dict):
        return {}
    if isinstance(raw_or_snap.get("data"), dict) and (
        "bp_list" in raw_or_snap["data"] or "camp1" in raw_or_snap["data"] or "battle_id" in raw_or_snap["data"]
    ):
        return raw_or_snap["data"]
    return raw_or_snap


def parse_bp_list(raw_or_snap: Any) -> list[dict[str, Any]]:
    """Parse official ``bp_list`` into normalized timeline steps.

    Each step: step, phase, action (ban|pick), camp, hero_id, hero_name, hero_icon,
    position, position_name, incomplete.
    When step count != 20, existing steps are returned with ``incomplete=True``.
    Does **not** feed V11 ``predict_probability`` features.
    """
    payload = _extract_battle_payload(raw_or_snap)
    bp_raw = payload.get("bp_list")
    if not isinstance(bp_raw, list) or not bp_raw:
        return []

    incomplete = len(bp_raw) != BP_EXPECTED_STEPS
    steps: list[dict[str, Any]] = []
    for idx, item in enumerate(bp_raw):
        if not isinstance(item, dict):
            continue
        is_pick = int(item.get("is_ban_or_pick", 0) or 0) == 1
        action = "pick" if is_pick else "ban"
        camp = int(item.get("camp", 0) or 0)
        position = int(item.get("position", 0) or 0)
        steps.append(
            {
                "step": idx,
                "phase": _bp_phase_for_step(idx, action),
                "action": action,
                "camp": camp,
                "camp_name": "蓝" if camp == 1 else "红" if camp == 2 else str(camp),
                "hero_id": item.get("hero_id"),
                "hero_name": str(item.get("hero_name") or "").strip(),
                "hero_icon": item.get("hero_icon") or "",
                "position": position,
                "position_name": BP_POSITION_CN.get(position, f"位{position}"),
                "incomplete": incomplete,
            }
        )
    return steps


def _read_json_file(path: Path) -> dict[str, Any] | None:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
    return None


def load_battle_final_payload(battle_id: str) -> tuple[dict[str, Any] | None, str]:
    """Load final-frame battle payload containing ``bp_list``.

    Prefers the latest snapshot under ``RAW_DIR/{battle_id}`` that has ``bp_list``;
    falls back to ``data/raw/{battle_id}.json``.
    Returns (payload, source_label).
    """
    battle_id = str(battle_id or "").strip()
    if not battle_id:
        return None, ""

    battle_dir = RAW_DIR / battle_id
    if battle_dir.is_dir():
        files = sorted(battle_dir.glob("*.json"))
        for path in reversed(files):
            payload = _read_json_file(path)
            if not payload:
                continue
            data = _extract_battle_payload(payload)
            bp = data.get("bp_list")
            if isinstance(bp, list) and bp:
                return data, f"raw_snapshots/{battle_id}/{path.name}"

    fallback = RAW_FALLBACK_DIR / f"{battle_id}.json"
    if fallback.is_file():
        payload = _read_json_file(fallback)
        if payload:
            data = _extract_battle_payload(payload)
            bp = data.get("bp_list")
            if isinstance(bp, list) and bp:
                return data, f"raw/{battle_id}.json"

    return None, ""


def load_battle_bp(battle_id: str) -> dict[str, Any]:
    """Load and parse BP for one battle (final snapshot or raw fallback)."""
    payload, source = load_battle_final_payload(battle_id)
    if not payload:
        return {
            "battle_id": str(battle_id),
            "steps": [],
            "incomplete": True,
            "source": "",
            "camp1_team": "",
            "camp2_team": "",
            "win_camp": 0,
            "picks_by_camp": {1: [], 2: []},
            "bans_by_camp": {1: [], 2: []},
        }

    steps = parse_bp_list(payload)
    incomplete = (not steps) or any(s.get("incomplete") for s in steps) or len(steps) != BP_EXPECTED_STEPS
    c1 = payload.get("camp1", {}) or {}
    c2 = payload.get("camp2", {}) or {}
    picks_by_camp: dict[int, list[dict[str, Any]]] = {1: [], 2: []}
    bans_by_camp: dict[int, list[dict[str, Any]]] = {1: [], 2: []}
    for step in steps:
        camp = int(step.get("camp", 0) or 0)
        if camp not in (1, 2):
            continue
        if step.get("action") == "pick":
            picks_by_camp[camp].append(step)
        else:
            bans_by_camp[camp].append(step)

    return {
        "battle_id": str(payload.get("battle_id") or battle_id),
        "steps": steps,
        "incomplete": incomplete,
        "source": source,
        "camp1_team": c1.get("team_name") or c1.get("team_abbreviation") or "Camp1",
        "camp2_team": c2.get("team_name") or c2.get("team_abbreviation") or "Camp2",
        "win_camp": int(payload.get("win_camp", 0) or 0),
        "picks_by_camp": picks_by_camp,
        "bans_by_camp": bans_by_camp,
    }


def load_rune_dict(path: Path = RUNE_DICT_PATH) -> dict[str, str]:
    """Load optional rune id→name map. Missing / empty file → {} (all 待映射)."""
    if not path.is_file():
        return {}
    payload = _read_json_file(path)
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in payload.items():
        kid = str(key).strip()
        name = str(value).strip() if value is not None else ""
        if kid and name:
            out[kid] = name
    return out


def parse_symbol_ids(
    raw: Any,
    rune_dict: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Split ``symbol_ids`` (``id+id+…``) and optionally map via ``rune_dict``.

    Without a dict hit: ``name='待映射'``, ``mapped=False``.
    Does **not** feed V11 ``predict_probability``.
    """
    text = str(raw or "").strip()
    if not text:
        return []
    mapping = rune_dict if rune_dict is not None else load_rune_dict()
    items: list[dict[str, Any]] = []
    for part in text.split("+"):
        rid = str(part).strip()
        if not rid:
            continue
        name = mapping.get(rid, "")
        mapped = bool(name)
        items.append(
            {
                "id": rid,
                "name": name if mapped else "待映射",
                "mapped": mapped,
            }
        )
    return items


def _parse_equip_slots(raw_list: Any) -> list[dict[str, Any]]:
    """Normalize BriefEquipList to exactly PLAYER_EQUIP_SLOTS slots (official names/icons)."""
    slots: list[dict[str, Any]] = []
    if isinstance(raw_list, list):
        for item in raw_list[:PLAYER_EQUIP_SLOTS]:
            if not isinstance(item, dict):
                continue
            equip_id = item.get("equip_id")
            name = str(item.get("equip_name") or "").strip()
            icon = str(item.get("equip_icon") or "").strip()
            empty = equip_id in (None, "", 0) and not name
            slots.append(
                {
                    "equip_id": equip_id,
                    "equip_name": name,
                    "equip_icon": icon,
                    "empty": empty,
                    "source": "官方",
                }
            )
    while len(slots) < PLAYER_EQUIP_SLOTS:
        slots.append(
            {
                "equip_id": None,
                "equip_name": "",
                "equip_icon": "",
                "empty": True,
                "source": "官方",
            }
        )
    return slots


def parse_battle_players(
    payload: Any,
    rune_dict: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Normalize ``battle_player_list`` into UI-ready player dicts.

    Each player: camp/position/KDA/gold/rates/equip_list/symbol_id_list/mvp flags.
    Equipment uses official ``equip_name`` / ``equip_icon`` (no local equip dict).
    Does **not** feed V11 ``predict_probability``.
    """
    data = _extract_battle_payload(payload)
    raw_players = data.get("battle_player_list")
    if not isinstance(raw_players, list) or not raw_players:
        return []

    mapping = rune_dict if rune_dict is not None else load_rune_dict()
    players: list[dict[str, Any]] = []
    for raw in raw_players:
        if not isinstance(raw, dict):
            continue
        camp = int(raw.get("camp", 0) or 0)
        position = int(raw.get("position", 0) or 0)
        pos_key = POSITIONS.get(position, "")
        pos_desc = str(raw.get("position_desc") or "").strip() or POSITION_CN.get(pos_key, f"位{position}")
        kills = int(raw.get("kill_num", 0) or 0)
        deaths = int(raw.get("death_num", 0) or 0)
        assists = int(raw.get("assist_num", 0) or 0)
        gold = int(raw.get("gold", 0) or 0)
        hurt = float(raw.get("hurt_to_hero_total", 0) or 0)
        be_hurt = float(raw.get("be_hurt_by_hero_total", 0) or 0)
        hurt_rate = float(raw.get("hurt_to_hero_total_rate", 0) or 0)
        be_hurt_rate = float(raw.get("be_hurt_by_hero_total_rate", 0) or 0)
        participation = float(raw.get("participation_rate", 0) or 0)
        level_raw = raw.get("level")
        try:
            level = int(level_raw) if level_raw not in (None, "") else None
        except (TypeError, ValueError):
            level = None
        symbol_raw = str(raw.get("symbol_ids") or "").strip()
        symbol_list = parse_symbol_ids(symbol_raw, mapping)
        equips = _parse_equip_slots(raw.get("BriefEquipList"))
        player_name = str(raw.get("player_name") or raw.get("actual_player_name") or "").strip()
        hero_name = str(raw.get("hero_name") or "").strip()
        is_mvp = int(raw.get("is_mvp", 0) or 0) == 1
        is_lose_mvp = int(raw.get("is_lose_mvp", 0) or 0) == 1
        gold_eff = (hurt / gold) if gold > 0 else 0.0
        be_hurt_eff = (be_hurt / gold) if gold > 0 else 0.0
        players.append(
            {
                "player_name": player_name,
                "hero_name": hero_name,
                "hero_id": raw.get("hero_id"),
                "hero_icon": raw.get("hero_icon") or "",
                "camp": camp,
                "camp_name": "蓝" if camp == 1 else "红" if camp == 2 else str(camp),
                "position": position,
                "position_key": pos_key,
                "position_name": pos_desc,
                "kill_num": kills,
                "death_num": deaths,
                "assist_num": assists,
                "kda_text": f"{kills}/{deaths}/{assists}",
                "gold": gold,
                "level": level,
                "participation_rate": participation,
                "hurt_to_hero_total": hurt,
                "be_hurt_by_hero_total": be_hurt,
                "hurt_to_hero_total_rate": hurt_rate,
                "be_hurt_by_hero_total_rate": be_hurt_rate,
                "hurt_per_gold": gold_eff,
                "be_hurt_per_gold": be_hurt_eff,
                "is_mvp": is_mvp,
                "is_lose_mvp": is_lose_mvp,
                "mvp_score": float(raw.get("mvp_score", 0) or 0),
                "equip_list": equips,
                "equip_ids": [e.get("equip_id") for e in equips if not e.get("empty")],
                "equip_names": [e.get("equip_name") for e in equips if not e.get("empty")],
                "symbol_ids_raw": symbol_raw,
                "symbol_id_list": symbol_list,
                "symbol_ids": [s["id"] for s in symbol_list],
                "runes_mapped": all(s.get("mapped") for s in symbol_list) if symbol_list else False,
                "team_name": str(raw.get("team_name") or "").strip(),
                "team_id": raw.get("team_id"),
                "source_stats": "官方",
                "source_equip": "官方",
                "source_rune": "官方" if (symbol_list and all(s.get("mapped") for s in symbol_list)) else "估算",
            }
        )
    return players


def load_battle_players_payload(battle_id: str) -> tuple[dict[str, Any] | None, str]:
    """Load latest payload that contains ``battle_player_list``.

    Prefers ``RAW_DIR/{battle_id}`` last frame with players; falls back to
    ``data/raw/{battle_id}.json``.
    """
    battle_id = str(battle_id or "").strip()
    if not battle_id:
        return None, ""

    battle_dir = RAW_DIR / battle_id
    if battle_dir.is_dir():
        files = sorted(battle_dir.glob("*.json"))
        for path in reversed(files):
            payload = _read_json_file(path)
            if not payload:
                continue
            data = _extract_battle_payload(payload)
            players = data.get("battle_player_list")
            if isinstance(players, list) and players:
                return data, f"raw_snapshots/{battle_id}/{path.name}"

    fallback = RAW_FALLBACK_DIR / f"{battle_id}.json"
    if fallback.is_file():
        payload = _read_json_file(fallback)
        if payload:
            data = _extract_battle_payload(payload)
            players = data.get("battle_player_list")
            if isinstance(players, list) and players:
                return data, f"raw/{battle_id}.json"

    return None, ""


def load_battle_players(battle_id: str) -> dict[str, Any]:
    """Load and parse players for one battle (latest snap or raw fallback)."""
    payload, source = load_battle_players_payload(battle_id)
    empty = {
        "battle_id": str(battle_id),
        "players": [],
        "source": "",
        "camp1_team": "",
        "camp2_team": "",
        "camp1_gold": 0,
        "camp2_gold": 0,
        "camp1_kill": 0,
        "camp2_kill": 0,
        "time_sec": 0,
        "minute": 0.0,
        "win_camp": 0,
        "rune_dict_loaded": False,
    }
    if not payload:
        return empty

    rune_dict = load_rune_dict()
    players = parse_battle_players(payload, rune_dict)
    c1 = payload.get("camp1", {}) or {}
    c2 = payload.get("camp2", {}) or {}
    time_sec = get_seconds(payload.get("game_duration"))
    return {
        "battle_id": str(payload.get("battle_id") or battle_id),
        "players": players,
        "source": source,
        "camp1_team": c1.get("team_name") or c1.get("team_abbreviation") or "Camp1",
        "camp2_team": c2.get("team_name") or c2.get("team_abbreviation") or "Camp2",
        "camp1_gold": int(c1.get("gold", 0) or 0),
        "camp2_gold": int(c2.get("gold", 0) or 0),
        "camp1_kill": int(c1.get("kill_num", 0) or 0),
        "camp2_kill": int(c2.get("kill_num", 0) or 0),
        "time_sec": int(time_sec),
        "minute": float(time_sec) / 60.0 if time_sec else 0.0,
        "win_camp": int(payload.get("win_camp", 0) or 0),
        "rune_dict_loaded": bool(rune_dict),
    }


def player_slot_key(player: dict[str, Any]) -> str:
    """Stable identity within a battle: camp + position (+ name fallback)."""
    camp = int(player.get("camp", 0) or 0)
    position = int(player.get("position", 0) or 0)
    name = str(player.get("player_name") or "").strip()
    return f"{camp}:{position}:{name}"


def load_player_gold_series(battle_id: str) -> dict[str, list[dict[str, Any]]]:
    """Collect per-player gold over multi-frame snaps under RAW_DIR.

    Returns ``{slot_key: [{"minute": float, "gold": int}, ...]}``.
    Empty when fewer than 2 frames have player gold.
    """
    battle_id = str(battle_id or "").strip()
    battle_dir = RAW_DIR / battle_id
    if not battle_dir.is_dir():
        return {}

    series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_sec: set[int] = set()
    for path in sorted(battle_dir.glob("*.json")):
        payload = _read_json_file(path)
        if not payload:
            continue
        data = _extract_battle_payload(payload)
        status = int(data.get("status", 0) or 0)
        if status not in (1, 2):
            continue
        sec = get_seconds(data.get("game_duration"))
        if sec in seen_sec:
            continue
        seen_sec.add(sec)
        raw_players = data.get("battle_player_list")
        if not isinstance(raw_players, list):
            continue
        minute = float(sec) / 60.0
        for raw in raw_players:
            if not isinstance(raw, dict):
                continue
            camp = int(raw.get("camp", 0) or 0)
            position = int(raw.get("position", 0) or 0)
            name = str(raw.get("player_name") or raw.get("actual_player_name") or "").strip()
            key = f"{camp}:{position}:{name}"
            series[key].append({"minute": minute, "gold": int(raw.get("gold", 0) or 0)})

    return {k: v for k, v in series.items() if len(v) >= 2}


def players_to_wide_df(players: list[dict[str, Any]]) -> pd.DataFrame:
    """Wide CSV-oriented table: identity + stats + equip/symbol id lists."""
    rows: list[dict[str, Any]] = []
    for p in players:
        equip_ids = p.get("equip_ids") or []
        symbol_ids = p.get("symbol_ids") or []
        rows.append(
            {
                "camp": p.get("camp"),
                "camp_name": p.get("camp_name"),
                "position": p.get("position"),
                "position_name": p.get("position_name"),
                "player_name": p.get("player_name"),
                "hero_name": p.get("hero_name"),
                "kill_num": p.get("kill_num"),
                "death_num": p.get("death_num"),
                "assist_num": p.get("assist_num"),
                "gold": p.get("gold"),
                "level": p.get("level"),
                "participation_rate": p.get("participation_rate"),
                "hurt_to_hero_total_rate": p.get("hurt_to_hero_total_rate"),
                "be_hurt_by_hero_total_rate": p.get("be_hurt_by_hero_total_rate"),
                "hurt_per_gold": p.get("hurt_per_gold"),
                "is_mvp": int(bool(p.get("is_mvp"))),
                "is_lose_mvp": int(bool(p.get("is_lose_mvp"))),
                "mvp_score": p.get("mvp_score"),
                "equip_ids": "+".join(str(x) for x in equip_ids if x is not None),
                "equip_names": "|".join(str(x) for x in (p.get("equip_names") or []) if x),
                "symbol_ids": "+".join(str(x) for x in symbol_ids if x),
            }
        )
    return pd.DataFrame(rows)


def _core_picks(pick_steps: list[dict[str, Any]], k: int = 3) -> frozenset[str]:
    names = [str(s.get("hero_name") or "").strip() for s in pick_steps if str(s.get("hero_name") or "").strip()]
    return frozenset(names[:k])


def _rate_pack(successes: int, n: int) -> dict[str, Any]:
    rate = (successes / n) if n > 0 else 0.0
    lo, hi = wilson_ci(successes, n)
    return {
        "k": int(successes),
        "n": int(n),
        "rate": float(rate),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "small_sample": n < BP_SMALL_SAMPLE_N,
    }


def aggregate_bp_meta(battle_ids: list[str] | None = None) -> dict[str, Any]:
    """Aggregate ban/pick/win rates over final snapshots for a battle window.

    Memory-only meta for dashboard; scans final frames with ``bp_list``.
    """
    if battle_ids is None:
        ids: list[str] = []
        if RAW_DIR.exists():
            ids.extend(p.name for p in RAW_DIR.iterdir() if p.is_dir())
        if RAW_FALLBACK_DIR.exists():
            ids.extend(p.stem for p in RAW_FALLBACK_DIR.glob("*.json"))
        battle_ids = sorted(set(ids))

    hero_ban: Counter[str] = Counter()
    hero_pick: Counter[str] = Counter()
    hero_win: Counter[str] = Counter()
    lineup_5: dict[frozenset[str], list[int]] = defaultdict(lambda: [0, 0])  # n, wins
    lineup_3: dict[frozenset[str], list[int]] = defaultdict(lambda: [0, 0])
    n_battles = 0

    for battle_id in battle_ids:
        payload, _ = load_battle_final_payload(str(battle_id))
        if not payload:
            continue
        steps = parse_bp_list(payload)
        if not steps:
            continue
        n_battles += 1
        win_camp = int(payload.get("win_camp", 0) or 0)
        banned: set[str] = set()
        picks_by_camp: dict[int, list[dict[str, Any]]] = {1: [], 2: []}
        for step in steps:
            name = str(step.get("hero_name") or "").strip()
            if not name:
                continue
            camp = int(step.get("camp", 0) or 0)
            if step.get("action") == "ban":
                banned.add(name)
            elif step.get("action") == "pick" and camp in (1, 2):
                picks_by_camp[camp].append(step)

        for name in banned:
            hero_ban[name] += 1

        for camp, pick_steps in picks_by_camp.items():
            names = [str(s.get("hero_name") or "").strip() for s in pick_steps if str(s.get("hero_name") or "").strip()]
            won = int(win_camp == camp)
            for name in names:
                hero_pick[name] += 1
                if won:
                    hero_win[name] += 1
            if len(names) >= 5:
                key5 = frozenset(names[:5])
                lineup_5[key5][0] += 1
                lineup_5[key5][1] += won
            core3 = _core_picks(pick_steps, 3)
            if len(core3) >= 3:
                lineup_3[core3][0] += 1
                lineup_3[core3][1] += won

    heroes: dict[str, dict[str, Any]] = {}
    all_heroes = set(hero_ban) | set(hero_pick)
    for name in all_heroes:
        ban_n = int(hero_ban.get(name, 0))
        pick_n = int(hero_pick.get(name, 0))
        win_n = int(hero_win.get(name, 0))
        heroes[name] = {
            "hero_name": name,
            "ban": _rate_pack(ban_n, n_battles),
            "pick": _rate_pack(pick_n, n_battles),
            "win": _rate_pack(win_n, pick_n),
        }

    return {
        "n_battles": n_battles,
        "heroes": heroes,
        "lineup_5": {tuple(sorted(k)): {"n": v[0], "wins": v[1]} for k, v in lineup_5.items()},
        "lineup_3": {tuple(sorted(k)): {"n": v[0], "wins": v[1]} for k, v in lineup_3.items()},
    }


def lookup_lineup_winrate(
    meta: dict[str, Any],
    pick_steps: list[dict[str, Any]],
    *,
    min_n: int = 1,
) -> dict[str, Any]:
    """Exact 5-hero set winrate; fall back to core-3 picks when insufficient."""
    names = [str(s.get("hero_name") or "").strip() for s in pick_steps if str(s.get("hero_name") or "").strip()]
    empty = {
        "level": "none",
        "level_label": "无样本",
        "heroes": names,
        "n": 0,
        "wins": 0,
        "rate": 0.0,
        "ci_low": 0.0,
        "ci_high": 0.0,
        "small_sample": True,
    }
    if not meta or not names:
        return empty

    key5 = tuple(sorted(names[:5]))
    pack5 = (meta.get("lineup_5") or {}).get(key5)
    if pack5 and int(pack5.get("n", 0) or 0) >= min_n:
        n = int(pack5["n"])
        wins = int(pack5["wins"])
        rate_pack = _rate_pack(wins, n)
        return {
            "level": "exact_5",
            "level_label": "五英雄精确",
            "heroes": list(key5),
            **rate_pack,
            "wins": wins,
        }

    core3 = tuple(sorted(_core_picks(pick_steps, 3)))
    pack3 = (meta.get("lineup_3") or {}).get(core3) if len(core3) >= 3 else None
    if pack3 and int(pack3.get("n", 0) or 0) >= min_n:
        n = int(pack3["n"])
        wins = int(pack3["wins"])
        rate_pack = _rate_pack(wins, n)
        return {
            "level": "core_3",
            "level_label": "核心3 pick",
            "heroes": list(core3),
            **rate_pack,
            "wins": wins,
        }

    if pack5:
        n = int(pack5.get("n", 0) or 0)
        wins = int(pack5.get("wins", 0) or 0)
        rate_pack = _rate_pack(wins, n)
        return {
            "level": "exact_5",
            "level_label": "五英雄精确",
            "heroes": list(key5),
            **rate_pack,
            "wins": wins,
        }

    return {**empty, "heroes": names[:5]}


def hero_meta_rows_for_battle(bp: dict[str, Any], meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows for this-battle heroes vs window ban/pick/win + Wilson CI."""
    heroes_meta = meta.get("heroes") or {}
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for step in bp.get("steps") or []:
        name = str(step.get("hero_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        h = heroes_meta.get(name) or {
            "ban": _rate_pack(0, int(meta.get("n_battles", 0) or 0)),
            "pick": _rate_pack(0, int(meta.get("n_battles", 0) or 0)),
            "win": _rate_pack(0, 0),
        }
        ban, pick, win = h["ban"], h["pick"], h["win"]
        small = ban["small_sample"] or pick["small_sample"] or win["small_sample"]
        rows.append(
            {
                "英雄": name,
                "本局动作": step.get("action"),
                "本局阵营": step.get("camp_name"),
                "本局分路": step.get("position_name") if step.get("action") == "pick" else "—",
                "ban率": ban["rate"],
                "ban_n": ban["n"],
                "ban_CI": f"[{ban['ci_low']:.1%}, {ban['ci_high']:.1%}]",
                "pick率": pick["rate"],
                "pick_n": pick["n"],
                "pick_CI": f"[{pick['ci_low']:.1%}, {pick['ci_high']:.1%}]",
                "胜率": win["rate"],
                "胜率_n": win["n"],
                "胜率_CI": f"[{win['ci_low']:.1%}, {win['ci_high']:.1%}]",
                "小样本": "小样本 · 仅供参考" if small else "",
            }
        )
    return rows


class FeatureBuilder:
    """Build model features and official explanation metrics from snapshots."""

    def __init__(self, team_winrate: dict[str, float] | None = None):
        self.team_winrate = team_winrate or {}

    def build(self, snap: dict[str, Any], history: list[dict[str, Any]] | deque | None = None) -> dict[str, float]:
        history = list(history or [])
        minute = max(int(snap.get("minute_bin") or snap.get("minute", 1)), 1)
        gold_diff = snap.get("camp1_gold", 0) - snap.get("camp2_gold", 0)
        total_gold = max(snap.get("camp1_gold", 0) + snap.get("camp2_gold", 0), 1)
        kill_diff = snap.get("camp1_kill", 0) - snap.get("camp2_kill", 0)
        total_kills = max(snap.get("camp1_kill", 0) + snap.get("camp2_kill", 0), 1)
        c1_kda = (snap.get("camp1_kill", 0) + snap.get("camp1_assist", 0)) / max(snap.get("camp1_death", 0), 1)
        c2_kda = (snap.get("camp2_kill", 0) + snap.get("camp2_assist", 0)) / max(snap.get("camp2_death", 0), 1)

        prev = self._previous_snapshot(snap, history)
        if prev:
            prev_gold_diff = prev.get("camp1_gold", 0) - prev.get("camp2_gold", 0)
            dt_min = max((snap.get("time_sec", 0) - prev.get("time_sec", 0)) / 60, 0.1)
            gold_delta = gold_diff - prev_gold_diff
            gold_velocity = gold_delta / dt_min
        else:
            gold_delta = 0.0
            gold_velocity = 0.0

        c1_wr = self.team_winrate.get(str(snap.get("camp1_team", "")), 0.5)
        c2_wr = self.team_winrate.get(str(snap.get("camp2_team", "")), 0.5)

        feats: dict[str, float] = {
            "gold_diff": float(gold_diff),
            "gold_diff_per_min": gold_diff / minute,
            "gold_ratio": gold_diff / total_gold,
            "kill_diff_per_min": kill_diff / minute,
            "kill_rate": kill_diff / total_kills,
            "assist_diff_per_min": (snap.get("camp1_assist", 0) - snap.get("camp2_assist", 0)) / minute,
            "death_diff": snap.get("camp1_death", 0) - snap.get("camp2_death", 0),
            "kda_diff": c1_kda - c2_kda,
            "tower_diff": snap.get("camp1_tower", 0) - snap.get("camp2_tower", 0),
            "minute_bin": float(minute),
            "gold_diff_delta": gold_delta,
            "gold_diff_velocity": gold_velocity,
            "tyrant_diff": snap.get("camp1_tyrant", 0) - snap.get("camp2_tyrant", 0),
            "dark_tyrant_diff": snap.get("camp1_dark_tyrant", 0) - snap.get("camp2_dark_tyrant", 0),
            # lord (= big_dragon) kept for compat but excluded from objective_score (legacy overlap)
            "lord_diff": snap.get("camp1_lord", 0) - snap.get("camp2_lord", 0),
            "prophet_diff": snap.get("camp1_prophet", 0) - snap.get("camp2_prophet", 0),
            "shadow_diff": snap.get("camp1_shadow", 0) - snap.get("camp2_shadow", 0),
            "storm_diff": snap.get("camp1_storm", 0) - snap.get("camp2_storm", 0),
            "team_winrate_diff": c1_wr - c2_wr,
        }

        for _, pos_name in POSITIONS.items():
            feats[f"gold_diff_{pos_name}"] = snap.get(f"c1_gold_{pos_name}", 0) - snap.get(f"c2_gold_{pos_name}", 0)
            feats[f"hurt_diff_{pos_name}"] = snap.get(f"c1_hurt_{pos_name}", 0) - snap.get(f"c2_hurt_{pos_name}", 0)
            feats[f"behurt_diff_{pos_name}"] = snap.get(f"c1_behurt_{pos_name}", 0) - snap.get(f"c2_behurt_{pos_name}", 0)
            feats[f"kill_diff_{pos_name}"] = snap.get(f"c1_kill_{pos_name}", 0) - snap.get(f"c2_kill_{pos_name}", 0)
            feats[f"death_diff_{pos_name}"] = snap.get(f"c1_death_{pos_name}", 0) - snap.get(f"c2_death_{pos_name}", 0)
            feats[f"level_diff_{pos_name}"] = snap.get(f"c1_level_{pos_name}", 0) - snap.get(f"c2_level_{pos_name}", 0)

        c1_carry = snap.get("c1_gold_mid", 0) + snap.get("c1_gold_adc", 0)
        c2_carry = snap.get("c2_gold_mid", 0) + snap.get("c2_gold_adc", 0)
        c1_hurt = sum(snap.get(f"c1_hurt_{pos}", 0) for pos in POSITIONS.values())
        c2_hurt = sum(snap.get(f"c2_hurt_{pos}", 0) for pos in POSITIONS.values())
        c1_behurt = sum(snap.get(f"c1_behurt_{pos}", 0) for pos in POSITIONS.values())
        c2_behurt = sum(snap.get(f"c2_behurt_{pos}", 0) for pos in POSITIONS.values())
        # Prefer prophet/shadow over legacy big_dragon(lord)
        objective_score = (
            feats["dark_tyrant_diff"] * 4
            + feats["storm_diff"] * 6
            + feats["tyrant_diff"] * 2
            + feats["prophet_diff"] * 2.0
            + feats["shadow_diff"] * 2.5
            + feats["tower_diff"] * 3.5
        )
        lane_abs = [abs(feats.get(f"gold_diff_{pos}", 0)) for pos in POSITIONS.values()]

        # --- derived: momentum / structure / windows (all causal) ---
        gold_accel = self._gold_diff_accel(snap, history, gold_diff, gold_velocity, prev)
        kill_mom = self._kill_momentum_diff(snap, history, kill_diff, minute)
        lane_crush = self._lane_crush_count(feats, thresh=800.0)
        hurt_conc = self._max_share_diff(
            [snap.get(f"c1_hurt_{p}", 0) for p in POSITIONS.values()],
            [snap.get(f"c2_hurt_{p}", 0) for p in POSITIONS.values()],
        )
        behurt_conc = self._max_share_diff(
            [snap.get(f"c1_behurt_{p}", 0) for p in POSITIONS.values()],
            [snap.get(f"c2_behurt_{p}", 0) for p in POSITIONS.values()],
        )
        roll4 = self._rolling_team_diff(snap, history, lookback_min=4, key1="camp1_gold", key2="camp2_gold")
        roll10 = self._rolling_team_diff(snap, history, lookback_min=10, key1="camp1_gold", key2="camp2_gold")
        roll4_jg = self._rolling_pos_gold_diff(snap, history, lookback_min=4, pos="jungle")
        roll4_adc = self._rolling_pos_gold_diff(snap, history, lookback_min=4, pos="adc")
        win35 = self._interval_team_diffs(snap, history, start_min=3, end_min=5)
        win911 = self._interval_team_diffs(snap, history, start_min=9, end_min=11)
        obj_convert = self._obj_tower_convert(snap, history, lookback_min=3)

        feats.update(
            {
                "carry_dominance": (c1_carry - c2_carry) / max(c1_carry + c2_carry, 1),
                "objective_value_score": objective_score,
                "lane_dominance_max": max(lane_abs) / total_gold if lane_abs else 0,
                "exp_diff_per_min": gold_diff / minute,
                "map_pressure_index": (feats["tower_diff"] * 0.45 + objective_score * 0.35 + feats["gold_ratio"] * 20) / 3,
                "resource_control_rate": objective_score / max(minute, 1),
                "carry_gold_share_diff": self._carry_share_diff(snap),
                "damage_conversion_diff": (c1_hurt / max(snap.get("camp1_gold", 0), 1)) - (c2_hurt / max(snap.get("camp2_gold", 0), 1)),
                "tempo_swing_score": gold_velocity / 1000 + feats["kill_diff_per_min"] * 0.6 + feats["tower_diff"] * 0.35,
                "late_game_scaling_proxy": (c1_carry - c2_carry) / max(total_gold, 1) + feats["storm_diff"] * 0.25,
                # new real features
                "gold_diff_accel": gold_accel,
                "kill_momentum_diff": kill_mom,
                "lane_crush_count": float(lane_crush),
                "hurt_conc_diff": hurt_conc,
                "behurt_conc_diff": behurt_conc,
                "gold_diff_roll4": roll4["delta"],
                "gold_diff_roll4_per_min": roll4["per_min"],
                "gold_diff_roll10": roll10["delta"],
                "gold_diff_roll10_per_min": roll10["per_min"],
                "gold_diff_jungle_roll4": roll4_jg["delta"],
                "gold_diff_adc_roll4": roll4_adc["delta"],
                "win35_kill_diff": win35["kill_diff"],
                "win35_death_diff": win35["death_diff"],
                "win35_hurt_diff": win35["hurt_diff"],
                "win911_kill_diff": win911["kill_diff"],
                "win911_death_diff": win911["death_diff"],
                "win911_hurt_diff": win911["hurt_diff"],
                "obj_tower_convert": obj_convert,
                "kill_diff_jungle": feats["kill_diff_jungle"],
                "kill_diff_adc": feats["kill_diff_adc"],
                "death_diff_jungle": feats["death_diff_jungle"],
                "death_diff_adc": feats["death_diff_adc"],
                "behurt_diff_top": feats["behurt_diff_top"],
                "behurt_diff_support": feats["behurt_diff_support"],
            }
        )
        return feats

    def explain(self, snap: dict[str, Any], feats: dict[str, float]) -> list[dict[str, Any]]:
        """Return business-readable factors for dashboard explanation panels."""
        factors = [
            ("经济节奏", feats.get("gold_ratio", 0), "双方总经济中的领先比例"),
            ("资源控制", feats.get("objective_value_score", 0) / 12, "暴君/主宰/防御塔带来的地图价值"),
            ("核心发育", feats.get("carry_dominance", 0), "中路与发育路的经济领先"),
            ("地图压力", feats.get("map_pressure_index", 0), "推塔、资源和经济形成的推进压力"),
            ("近期动量", feats.get("tempo_swing_score", 0), "最近一段时间优势扩大的速度"),
            ("伤害转化", feats.get("damage_conversion_diff", 0), "每单位经济转化为输出的效率"),
            ("金差加速", feats.get("gold_diff_accel", 0) / 2000, "经济领先是在扩大还是收窄"),
            ("击杀动量", feats.get("kill_momentum_diff", 0), "近窗击杀节奏相对全场均值"),
        ]
        rows = []
        for name, value, desc in factors:
            signed_value = float(np.clip(value, -1.0, 1.0))
            leader = snap.get("camp1_team") if signed_value >= 0 else snap.get("camp2_team")
            rows.append(
                {
                    "factor": name,
                    "value": signed_value,
                    "abs_value": abs(signed_value),
                    "leader": leader,
                    "description": desc,
                }
            )
        return sorted(rows, key=lambda x: x["abs_value"], reverse=True)

    @staticmethod
    def _previous_snapshot(snap: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any] | None:
        cur_t = snap.get("time_sec", 0)
        for item in reversed(history):
            if item.get("time_sec", 0) < cur_t:
                return item
        return None

    @staticmethod
    def _snap_at_or_before(history: list[dict[str, Any]], target_minute: float) -> dict[str, Any] | None:
        """Latest history snap with minute_bin <= target_minute."""
        best = None
        for item in history:
            m = float(item.get("minute_bin") or item.get("minute") or 0)
            if m <= target_minute + 1e-6:
                if best is None or m >= float(best.get("minute_bin") or best.get("minute") or 0):
                    best = item
        return best

    @classmethod
    def _gold_diff_accel(
        cls,
        snap: dict[str, Any],
        history: list[dict[str, Any]],
        gold_diff: float,
        gold_velocity: float,
        prev: dict[str, Any] | None,
    ) -> float:
        if not prev:
            return 0.0
        prev2 = cls._previous_snapshot(prev, history)
        if not prev2:
            return 0.0
        prev_gd = prev.get("camp1_gold", 0) - prev.get("camp2_gold", 0)
        prev2_gd = prev2.get("camp1_gold", 0) - prev2.get("camp2_gold", 0)
        dt0 = max((prev.get("time_sec", 0) - prev2.get("time_sec", 0)) / 60, 0.1)
        v0 = (prev_gd - prev2_gd) / dt0
        return float(gold_velocity - v0)

    @classmethod
    def _kill_momentum_diff(
        cls,
        snap: dict[str, Any],
        history: list[dict[str, Any]],
        kill_diff: float,
        minute: int,
    ) -> float:
        if minute < 3:
            return 0.0
        past = cls._snap_at_or_before(history, minute - 3)
        if past is None:
            return 0.0
        past_kd = past.get("camp1_kill", 0) - past.get("camp2_kill", 0)
        dt = max(minute - float(past.get("minute_bin") or past.get("minute") or 1), 0.5)
        recent_rate = (kill_diff - past_kd) / dt
        cum_rate = kill_diff / max(minute, 1)
        return float(recent_rate - cum_rate)

    @staticmethod
    def _lane_crush_count(feats: dict[str, float], thresh: float = 800.0) -> int:
        c1 = c2 = 0
        for pos in POSITIONS.values():
            gd = float(feats.get(f"gold_diff_{pos}", 0.0))
            if gd >= thresh:
                c1 += 1
            elif gd <= -thresh:
                c2 += 1
        return c1 - c2

    @staticmethod
    def _max_share_diff(c1_vals: list[float], c2_vals: list[float]) -> float:
        s1 = float(sum(c1_vals))
        s2 = float(sum(c2_vals))
        m1 = (max(c1_vals) / s1) if s1 > 0 else 0.0
        m2 = (max(c2_vals) / s2) if s2 > 0 else 0.0
        return float(m1 - m2)

    @classmethod
    def _rolling_team_diff(
        cls,
        snap: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        lookback_min: int,
        key1: str,
        key2: str,
    ) -> dict[str, float]:
        minute = max(int(snap.get("minute_bin") or snap.get("minute", 1)), 1)
        cur = float(snap.get(key1, 0) or 0) - float(snap.get(key2, 0) or 0)
        if minute < 2:
            return {"delta": 0.0, "per_min": 0.0}
        past = cls._snap_at_or_before(history, max(minute - lookback_min, 1))
        if past is None:
            # fall back to earliest history or zero
            if not history:
                return {"delta": cur, "per_min": cur / max(minute, 1)}
            past = history[0]
        past_v = float(past.get(key1, 0) or 0) - float(past.get(key2, 0) or 0)
        dt = max(minute - float(past.get("minute_bin") or past.get("minute") or 1), 0.5)
        delta = cur - past_v
        return {"delta": float(delta), "per_min": float(delta / dt)}

    @classmethod
    def _rolling_pos_gold_diff(
        cls,
        snap: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        lookback_min: int,
        pos: str,
    ) -> dict[str, float]:
        return cls._rolling_team_diff(
            snap,
            history,
            lookback_min=lookback_min,
            key1=f"c1_gold_{pos}",
            key2=f"c2_gold_{pos}",
        )

    @classmethod
    def _interval_team_diffs(
        cls,
        snap: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        start_min: int,
        end_min: int,
    ) -> dict[str, float]:
        """Diffs accrued inside [start_min, end_min]; 0 if current minute < end_min."""
        minute = max(int(snap.get("minute_bin") or snap.get("minute", 1)), 1)
        empty = {"kill_diff": 0.0, "death_diff": 0.0, "hurt_diff": 0.0}
        if minute < end_min:
            return empty
        # end anchor: snap at end_min (or current if we're past and want closed window at end_min)
        end_snap = cls._snap_at_or_before(history + [snap], float(end_min))
        start_snap = cls._snap_at_or_before(history, float(start_min))
        if end_snap is None:
            return empty
        if start_snap is None:
            start_snap = {"camp1_kill": 0, "camp2_kill": 0, "camp1_death": 0, "camp2_death": 0}
            for pos in POSITIONS.values():
                start_snap[f"c1_hurt_{pos}"] = 0
                start_snap[f"c2_hurt_{pos}"] = 0

        def _kd(s: dict) -> float:
            return float(s.get("camp1_kill", 0) - s.get("camp2_kill", 0))

        def _dd(s: dict) -> float:
            return float(s.get("camp1_death", 0) - s.get("camp2_death", 0))

        def _hd(s: dict) -> float:
            return float(
                sum(s.get(f"c1_hurt_{p}", 0) for p in POSITIONS.values())
                - sum(s.get(f"c2_hurt_{p}", 0) for p in POSITIONS.values())
            )

        return {
            "kill_diff": _kd(end_snap) - _kd(start_snap),
            "death_diff": _dd(end_snap) - _dd(start_snap),
            "hurt_diff": _hd(end_snap) - _hd(start_snap),
        }

    @classmethod
    def _obj_tower_convert(cls, snap: dict[str, Any], history: list[dict[str, Any]], lookback_min: int = 3) -> float:
        """Tower-diff change in lookback after any objective gain (excl. legacy lord)."""
        minute = max(int(snap.get("minute_bin") or snap.get("minute", 1)), 1)
        if minute < lookback_min + 1:
            return 0.0
        past = cls._snap_at_or_before(history, minute - lookback_min)
        if past is None:
            return 0.0

        def _obj_counts(s: dict) -> tuple[float, float]:
            keys = ("tyrant", "dark_tyrant", "prophet", "shadow", "storm")
            c1 = sum(float(s.get(f"camp1_{k}", 0) or 0) for k in keys)
            c2 = sum(float(s.get(f"camp2_{k}", 0) or 0) for k in keys)
            return c1, c2

        c1_now, c2_now = _obj_counts(snap)
        c1_past, c2_past = _obj_counts(past)
        c1_gain = c1_now - c1_past
        c2_gain = c2_now - c2_past
        if c1_gain <= 0 and c2_gain <= 0:
            return 0.0
        tower_now = float(snap.get("camp1_tower", 0) - snap.get("camp2_tower", 0))
        tower_past = float(past.get("camp1_tower", 0) - past.get("camp2_tower", 0))
        tower_delta = tower_now - tower_past
        # Sign by who took more objectives in the window
        side = 1.0 if c1_gain > c2_gain else (-1.0 if c2_gain > c1_gain else 0.0)
        return float(tower_delta * side) if side != 0 else 0.0

    @staticmethod
    def _carry_share_diff(snap: dict[str, Any]) -> float:
        c1_gold = max(snap.get("camp1_gold", 0), 1)
        c2_gold = max(snap.get("camp2_gold", 0), 1)
        c1_carry = snap.get("c1_gold_mid", 0) + snap.get("c1_gold_adc", 0)
        c2_carry = snap.get("c2_gold_mid", 0) + snap.get("c2_gold_adc", 0)
        return c1_carry / c1_gold - c2_carry / c2_gold

def _apply_calibrator(artifact: dict[str, Any], prob_raw: float, *, which: str = "auto") -> float:
    if which == "early":
        calibrator = artifact.get("calibrator_early") or artifact.get("calibrator")
    elif which == "midlate":
        calibrator = artifact.get("calibrator_midlate") or artifact.get("calibrator")
    else:
        calibrator = artifact.get("calibrator")
    if calibrator is None:
        return float(prob_raw)
    try:
        if hasattr(calibrator, "predict"):
            out = calibrator.predict(np.array([prob_raw], dtype=float))
            return float(out[0])
        if hasattr(calibrator, "predict_proba"):
            out = calibrator.predict_proba(np.array([[prob_raw]], dtype=float))[:, 1]
            return float(out[0])
    except Exception:
        return float(prob_raw)
    return float(prob_raw)


def _apply_time_shrinkage(prob: float, minute: int) -> float:
    if minute <= 2:
        conf = 0.4
    elif minute <= 5:
        conf = 0.5 + (minute - 2) * 0.1
    elif minute <= 8:
        conf = 0.8 + (minute - 5) * 0.067
    else:
        conf = 1.0
    return 0.5 + (prob - 0.5) * conf


def _blend_weight(minute: float, blend_start: float = 6.0, blend_end: float = 10.0) -> float:
    m = float(minute)
    if m <= blend_start:
        return 0.0
    if m >= blend_end:
        return 1.0
    return (m - blend_start) / max(blend_end - blend_start, 1e-6)


def gold_prior_prob(gold_ratio: float, k: float = 10.0) -> float:
    """Weak prior from gold lead: sigmoid(k * gold_ratio)."""
    x = float(np.clip(gold_ratio, -1.0, 1.0))
    return float(1.0 / (1.0 + np.exp(-k * x)))


def apply_gold_consistency_guard(
    prob: float,
    feats: dict[str, float],
    *,
    enabled: bool = True,
    minute: int | None = None,
) -> tuple[float, dict[str, float]]:
    """Blend model prob toward gold prior when they clash with clear economy.

    Mid/late (minute>=8): stronger pull — forbids win-prob floating against economy
    (V10 midlate isotonic failure mode).
    Late-early (minute 5–7): soft pull only on severe sign clash (|gold_diff|>=1200),
    so stomps are not reported as 0.8+ for the trailing side.
    Skip aggressive pull when major objectives support the model side (true comebacks).
    """
    meta = {"gold_guard_applied": 0.0, "p_gold": 0.5, "gold_guard_alpha": 0.0}
    if not enabled:
        return float(prob), meta
    minute = int(minute if minute is not None else feats.get("minute_bin", 1))
    gold_ratio = float(feats.get("gold_ratio", 0.0))
    p_gold = gold_prior_prob(gold_ratio)
    meta["p_gold"] = p_gold
    if minute < 5:
        return float(prob), meta

    gold_diff = float(feats.get("gold_diff", feats.get("gold_diff_per_min", 0.0) * max(minute, 1)))
    soft_early = minute < 8
    min_gold = 1200 if soft_early else 1200
    if abs(gold_ratio) < 0.02 and abs(gold_diff) < min_gold:
        return float(prob), meta
    # Soft early: only act on clear gold lead, ignore tiny ratio noise
    if soft_early and abs(gold_diff) < 1200:
        return float(prob), meta

    p = float(prob)
    # Major objectives can justify disagreeing with gold (comeback path)
    big_obj = (
        float(feats.get("lord_diff", 0.0))
        + 1.5 * float(feats.get("storm_diff", 0.0))
        + 0.5 * float(feats.get("tyrant_diff", 0.0))
        + 0.75 * float(feats.get("dark_tyrant_diff", 0.0))
    )
    if p >= 0.5 and gold_diff < 0 and big_obj >= 1.0:
        return p, meta
    if p < 0.5 and gold_diff > 0 and big_obj <= -1.0:
        return p, meta

    clash = abs(p - p_gold)
    sign_clash = ((p - 0.5) * gold_ratio < 0) or ((p - 0.5) * gold_diff < 0 and abs(gold_diff) >= 1200)
    if soft_early:
        # Require direction clash; tiny clash alone is not enough
        if not sign_clash or clash <= 0.18:
            return p, meta
        alpha = 0.18 + min(0.17, max(0.0, clash - 0.18) * 0.45)
        if abs(gold_diff) >= 2500:
            alpha += 0.06
        alpha = float(np.clip(alpha, 0.15, 0.40))
    else:
        if clash <= 0.20 and not sign_clash:
            return p, meta
        # alpha ~0.25→0.55 per plan
        alpha = 0.25 + min(0.25, (minute - 8) * 0.03) + min(0.15, max(0.0, clash - 0.20) * 0.5)
        if abs(gold_diff) >= 2500:
            alpha += 0.08
        alpha = float(np.clip(alpha, 0.25, 0.55))

    blended = (1.0 - alpha) * p + alpha * p_gold

    # Cap toward gold prior only on clear direction clashes without objective support
    if sign_clash and clash >= 0.12 and gold_diff <= -1200:
        slack = 0.06 if soft_early else (0.04 if abs(gold_diff) < 3500 else 0.0)
        blended = min(blended, p_gold + slack)
    elif sign_clash and clash >= 0.12 and gold_diff >= 1200:
        slack = 0.06 if soft_early else (0.04 if abs(gold_diff) < 3500 else 0.0)
        blended = max(blended, p_gold - slack)

    meta["gold_guard_applied"] = 1.0
    meta["gold_guard_alpha"] = alpha
    return float(np.clip(blended, 0.02, 0.98)), meta


# --- P07 win-prob benchmark (V11 vs gold prior; official curve not fabricated) ---

WINPROB_CONFLICT_THRESHOLD = 0.15
# README / product doc fallback when train_status & artifact lack holdout fields
V11_README_HOLDOUT_BRIER = {"early": None, "mid": None, "all": None, "late": None}


def approx_gold_ratio_from_diff(gold_diff: float, minute: float) -> float:
    """Approximate gold_ratio when total gold is unknown (CSV-only path).

    Assumes combined economy grows ~2500/min for 10 players, floored so the
    ratio stays in [-1, 1]. Mark callers with ``gold_ratio_approx=True``.
    """
    gd = float(gold_diff or 0.0)
    m = max(float(minute or 1.0), 1.0)
    total = max(abs(gd) * 2.0 + 2000.0, m * 2500.0)
    return float(np.clip(gd / max(total, 1.0), -1.0, 1.0))


def _prediction_csv_path(battle_id: str) -> Path:
    return PREDICTION_DIR / f"{str(battle_id).strip()}.csv"


def _load_prediction_csv_rows(battle_id: str) -> pd.DataFrame:
    path = _prediction_csv_path(battle_id)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.ParserError, UnicodeDecodeError):
        return pd.DataFrame()


def _downsample_pred_by_minute(df: pd.DataFrame) -> pd.DataFrame:
    """Keep last row per minute_bin (live CSV may repeat end-game polls)."""
    if df.empty:
        return df
    out = df.copy()
    if "minute" not in out.columns and "minute_bin" in out.columns:
        out["minute"] = pd.to_numeric(out["minute_bin"], errors="coerce")
    out["minute"] = pd.to_numeric(out.get("minute"), errors="coerce")
    out = out.dropna(subset=["minute"])
    if out.empty:
        return out
    out["minute_bin"] = out["minute"].map(lambda m: max(int(m), 1))
    # Prefer last observation per bin (most recent poll for that minute)
    return out.drop_duplicates(subset=["minute_bin"], keep="last").sort_values("minute").reset_index(drop=True)


def _snap_economy_by_minute(battle_id: str) -> dict[int, dict[str, float]]:
    """minute_bin -> gold_ratio / gold_diff from FeatureBuilder (official snaps)."""
    battle_dir, _ = _resolve_battle_snapshot_dir(battle_id)
    if battle_dir is None:
        return {}
    snaps = load_battle_jsons(battle_dir)
    if not snaps:
        return {}
    builder = FeatureBuilder()
    history: deque[dict[str, Any]] = deque(maxlen=40)
    out: dict[int, dict[str, float]] = {}
    for snap in snaps:
        history.append(snap)
        mb = max(int(snap.get("minute_bin") or snap.get("minute") or 1), 1)
        if mb in out:
            continue
        feats = builder.build(snap, list(history)[:-1])
        out[mb] = {
            "gold_ratio": float(feats.get("gold_ratio", 0.0) or 0.0),
            "gold_diff": float(feats.get("gold_diff", 0.0) or 0.0),
            "minute": float(snap.get("minute") or mb),
        }
    return out


def _replay_v11_timeline(battle_id: str) -> pd.DataFrame:
    """Re-run V11 on raw snapshots when prediction CSV is missing."""
    battle_dir, _ = _resolve_battle_snapshot_dir(battle_id)
    if battle_dir is None:
        return pd.DataFrame()
    try:
        artifact = load_model()
    except Exception:
        artifact = None
    if not artifact:
        return pd.DataFrame()
    snaps = load_battle_jsons(battle_dir)
    if not snaps:
        return pd.DataFrame()
    history: deque[dict[str, Any]] = deque(maxlen=40)
    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    for snap in snaps:
        minute_bin = max(int(snap.get("minute_bin") or snap.get("minute") or 1), 1)
        history.append(snap)
        if minute_bin in seen:
            continue
        seen.add(minute_bin)
        prob, feats, _ = predict_probability(artifact, snap, list(history))
        rows.append(
            {
                "minute": float(snap.get("minute") or minute_bin),
                "minute_bin": minute_bin,
                "camp1_win_prob": float(prob),
                "gold_diff": float(snap.get("camp1_gold", 0) or 0) - float(snap.get("camp2_gold", 0) or 0),
                "gold_guard_applied": float(feats.get("_gold_guard_applied", 0) or 0),
                "low_confidence": bool(feats.get("_low_confidence", 0)),
                "win_camp": int(snap.get("win_camp", 0) or 0),
            }
        )
    return pd.DataFrame(rows)


def build_winprob_benchmark(battle_id: str) -> pd.DataFrame:
    """Build V11 vs gold-prior benchmark series for one battle (P07).

    Columns
    -------
    minute, p_v11, p_gold, gold_diff, gold_ratio, low_confidence,
    gold_guard_applied, phase, delta_vs_prior

    Metadata (``df.attrs``)
    -----------------------
    official_available : always False this round (do **not** invent p_official)
    source : ``csv`` | ``replay`` | ``empty``
    gold_ratio_approx : True when ratio came from gold_diff heuristic
    battle_id, camp1_team, camp2_team, win_camp, conflict_threshold
    """
    battle_id = str(battle_id or "").strip()
    empty = pd.DataFrame(
        columns=[
            "minute",
            "p_v11",
            "p_gold",
            "gold_diff",
            "gold_ratio",
            "low_confidence",
            "gold_guard_applied",
            "phase",
            "delta_vs_prior",
        ]
    )
    empty.attrs.update(
        {
            "official_available": False,
            "source": "empty",
            "gold_ratio_approx": False,
            "battle_id": battle_id,
            "camp1_team": "",
            "camp2_team": "",
            "win_camp": 0,
            "conflict_threshold": WINPROB_CONFLICT_THRESHOLD,
            "message": "缺少 battle_id" if not battle_id else "暂无预测时间线",
        }
    )
    if not battle_id:
        return empty

    source = "empty"
    raw = _load_prediction_csv_rows(battle_id)
    if not raw.empty and ("camp1_win_prob" in raw.columns or "prob" in raw.columns):
        base = _downsample_pred_by_minute(raw)
        source = "csv"
    else:
        base = _replay_v11_timeline(battle_id)
        source = "replay" if not base.empty else "empty"

    if base.empty:
        empty.attrs["source"] = source
        empty.attrs["message"] = (
            f"未找到 `{battle_id}` 的 predictions CSV，且无法从 raw 回放。"
            "请启动监控或确认 raw_snapshots / 模型可用。"
        )
        return empty

    if "camp1_win_prob" not in base.columns and "prob" in base.columns:
        base = base.copy()
        base["camp1_win_prob"] = pd.to_numeric(base["prob"], errors="coerce")
    base["camp1_win_prob"] = pd.to_numeric(base["camp1_win_prob"], errors="coerce")
    base["minute"] = pd.to_numeric(base["minute"], errors="coerce")
    base = base.dropna(subset=["camp1_win_prob", "minute"]).copy()
    if base.empty:
        empty.attrs["source"] = source
        empty.attrs["message"] = "预测时间线存在但无有效 minute / camp1_win_prob"
        return empty

    if "minute_bin" not in base.columns:
        base["minute_bin"] = base["minute"].map(lambda m: max(int(m), 1))
    if "gold_diff" not in base.columns:
        base["gold_diff"] = 0.0
    base["gold_diff"] = pd.to_numeric(base["gold_diff"], errors="coerce").fillna(0.0)

    snap_eco = _snap_economy_by_minute(battle_id)
    any_approx = False
    rows: list[dict[str, Any]] = []
    for _, r in base.iterrows():
        minute = float(r["minute"])
        mb = max(int(r.get("minute_bin") or minute or 1), 1)
        p_v11 = float(np.clip(float(r["camp1_win_prob"]), 0.0, 1.0))
        gold_diff = float(r["gold_diff"])
        eco = snap_eco.get(mb)
        if eco is not None:
            gold_ratio = float(eco["gold_ratio"])
            gold_diff = float(eco.get("gold_diff", gold_diff))
            ratio_approx = False
        else:
            gold_ratio = approx_gold_ratio_from_diff(gold_diff, minute)
            ratio_approx = True
            any_approx = True

        p_gold = gold_prior_prob(gold_ratio)

        if "gold_guard_applied" in r.index and pd.notna(r.get("gold_guard_applied")):
            try:
                guard = float(r["gold_guard_applied"]) > 0.5
            except (TypeError, ValueError):
                guard = False
        else:
            # Reconstruct guard flag from prior clash (no fake official numbers)
            _, gmeta = apply_gold_consistency_guard(
                p_v11,
                {"gold_ratio": gold_ratio, "gold_diff": gold_diff},
                enabled=True,
                minute=mb,
            )
            guard = float(gmeta.get("gold_guard_applied", 0)) > 0.5

        if "low_confidence" in r.index and pd.notna(r.get("low_confidence")):
            low_conf = bool(r["low_confidence"])
        else:
            low_conf = bool(prediction_confidence(minute, p_v11).get("low_confidence"))

        rows.append(
            {
                "minute": minute,
                "p_v11": p_v11,
                "p_gold": float(p_gold),
                "gold_diff": gold_diff,
                "gold_ratio": gold_ratio,
                "gold_ratio_approx": ratio_approx,
                "low_confidence": low_conf,
                "gold_guard_applied": bool(guard),
                "phase": phase_of_minute(minute),
                "delta_vs_prior": float(p_v11 - p_gold),
            }
        )

    out = pd.DataFrame(rows)
    camp1 = str(base.iloc[-1].get("camp1_team", "") or "") if "camp1_team" in base.columns else ""
    camp2 = str(base.iloc[-1].get("camp2_team", "") or "") if "camp2_team" in base.columns else ""
    win_camp = 0
    if "win_camp" in base.columns:
        try:
            win_camp = int(pd.to_numeric(base["win_camp"], errors="coerce").dropna().iloc[-1])
        except (IndexError, ValueError, TypeError):
            win_camp = 0

    out.attrs.update(
        {
            "official_available": False,  # never fabricate p_official
            "source": source,
            "gold_ratio_approx": bool(any_approx),
            "battle_id": battle_id,
            "camp1_team": camp1,
            "camp2_team": camp2,
            "win_camp": win_camp,
            "conflict_threshold": WINPROB_CONFLICT_THRESHOLD,
            "message": "",
        }
    )
    return out


def summarize_winprob_benchmark_phases(
    df: pd.DataFrame,
    *,
    win_camp: int | None = None,
    conflict_threshold: float = WINPROB_CONFLICT_THRESHOLD,
) -> pd.DataFrame:
    """Per-phase MAE vs prior, conflict rate; optional Brier vs true winner."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["phase", "n", "mae_vs_prior", "conflict_rate", "brier_vs_label"])
    wc = int(win_camp if win_camp is not None else (df.attrs.get("win_camp") or 0))
    label = None
    if wc in (1, 2):
        label = 1.0 if wc == 1 else 0.0

    rows: list[dict[str, Any]] = []
    for phase in ("early", "mid", "late", "all"):
        sub = df if phase == "all" else df[df["phase"] == phase]
        n = int(len(sub))
        if n == 0:
            rows.append(
                {
                    "phase": phase,
                    "n": 0,
                    "mae_vs_prior": float("nan"),
                    "conflict_rate": float("nan"),
                    "brier_vs_label": float("nan"),
                }
            )
            continue
        delta = pd.to_numeric(sub["delta_vs_prior"], errors="coerce").abs()
        mae = float(delta.mean())
        conflict_rate = float((delta >= float(conflict_threshold)).mean())
        brier = float("nan")
        if label is not None and "p_v11" in sub.columns:
            p = pd.to_numeric(sub["p_v11"], errors="coerce").clip(1e-6, 1 - 1e-6)
            brier = float(np.mean((p - label) ** 2))
        rows.append(
            {
                "phase": phase,
                "n": n,
                "mae_vs_prior": mae,
                "conflict_rate": conflict_rate,
                "brier_vs_label": brier,
            }
        )
    return pd.DataFrame(rows)


def load_holdout_badge_metrics() -> dict[str, Any]:
    """Holdout Brier badge: train_status → artifact → explicitly unavailable."""
    badge: dict[str, Any] = {
        "version": "unknown",
        "model_name": "",
        "trained_at": "",
        "source": "unavailable",
        "early_brier": V11_README_HOLDOUT_BRIER["early"],
        "mid_brier": V11_README_HOLDOUT_BRIER["mid"],
        "all_brier": V11_README_HOLDOUT_BRIER["all"],
        "late_brier": V11_README_HOLDOUT_BRIER["late"],
        "note": "未提供本地模型或可验证测试指标",
    }
    # 1) train_status.json
    status_path = REALTIME_DIR / "train_status.json"
    if status_path.exists():
        try:
            train = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            train = {}
        early = train.get("holdout_early_brier")
        mid = train.get("holdout_mid_brier")
        all_b = train.get("holdout_real_brier") or train.get("holdout_all_brier")
        if early not in (None, "") or mid not in (None, "") or all_b not in (None, ""):
            badge.update(
                {
                    "version": str(train.get("model_name") or train.get("version") or "V11"),
                    "model_name": str(train.get("model_name") or ""),
                    "trained_at": str(train.get("trained_at") or train.get("updated_at") or ""),
                    "source": "train_status",
                    "early_brier": float(early) if early not in (None, "") else badge["early_brier"],
                    "mid_brier": float(mid) if mid not in (None, "") else badge["mid_brier"],
                    "all_brier": float(all_b) if all_b not in (None, "") else badge["all_brier"],
                    "late_brier": float(train["holdout_late_brier"])
                    if train.get("holdout_late_brier") not in (None, "")
                    else badge["late_brier"],
                    "note": "来自 train_status.json",
                }
            )
            return badge

    # 2) model artifact
    try:
        artifact = load_model()
    except Exception:
        artifact = None
    if artifact and isinstance(artifact, dict):
        hold = artifact.get("holdout_real") or {}
        if hold:
            badge.update(
                {
                    "version": str(artifact.get("version") or "V11"),
                    "model_name": str(artifact.get("model_name") or ""),
                    "trained_at": str(artifact.get("trained_at") or ""),
                    "source": "artifact",
                    "early_brier": float((hold.get("early") or {}).get("brier", badge["early_brier"])),
                    "mid_brier": float((hold.get("mid") or {}).get("brier", badge["mid_brier"])),
                    "all_brier": float((hold.get("all") or {}).get("brier", badge["all_brier"])),
                    "late_brier": float((hold.get("late") or {}).get("brier"))
                    if (hold.get("late") or {}).get("brier") is not None
                    else badge["late_brier"],
                    "note": "来自模型 artifact holdout_real",
                }
            )
            return badge

    return badge


def classify_battle_swing(snapshots: list[dict[str, Any]], win_camp: int) -> dict[str, Any]:
    """Classify comeback / swing from gold trajectory vs final winner."""
    result = {
        "comeback": False,
        "swing": False,
        "early_avg_gold_diff": 0.0,
        "mid_avg_gold_diff": 0.0,
        "win_camp": int(win_camp),
    }
    if not snapshots or win_camp not in (1, 2):
        return result
    early = [s for s in snapshots if max(int(s.get("minute", s.get("minute_bin", 0)) or 0), 1) <= 8]
    mid = [
        s
        for s in snapshots
        if 9 <= max(int(s.get("minute", s.get("minute_bin", 0)) or 0), 1) <= 12
    ]
    if len(early) >= 2:
        early_gd = float(np.mean([s.get("camp1_gold", 0) - s.get("camp2_gold", 0) for s in early]))
        result["early_avg_gold_diff"] = early_gd
        early_favors_c1 = early_gd > 0
        winner_is_c1 = win_camp == 1
        if early_favors_c1 != winner_is_c1 and abs(early_gd) >= 80:
            result["comeback"] = True
    if len(early) >= 2 and len(mid) >= 1:
        mid_gd = float(np.mean([s.get("camp1_gold", 0) - s.get("camp2_gold", 0) for s in mid]))
        result["mid_avg_gold_diff"] = mid_gd
        early_gd = result["early_avg_gold_diff"]
        if abs(early_gd) >= 80 and abs(mid_gd) >= 80 and (early_gd > 0) != (mid_gd > 0):
            result["swing"] = True
    return result


def predict_probability(artifact: dict[str, Any], snap: dict[str, Any], history: list[dict[str, Any]] | deque | None = None) -> tuple[float, dict[str, float], list[dict[str, Any]]]:
    builder = FeatureBuilder(artifact.get("team_winrate", {}))
    feats = builder.build(snap, history)
    minute = int(feats.get("minute_bin", 1))

    model_early = artifact.get("model_early")
    model_midlate = artifact.get("model_midlate") or artifact.get("model")
    is_blend = artifact.get("version") in ("V10", "V11") or model_early is not None

    if is_blend and model_early is not None and model_midlate is not None:
        early_cols = artifact.get("early_feature_columns") or artifact.get("feature_columns", [])
        mid_cols = artifact.get("feature_columns", [])
        x_e = pd.DataFrame([[feats.get(col, 0.0) for col in early_cols]], columns=early_cols)
        x_m = pd.DataFrame([[feats.get(col, 0.0) for col in mid_cols]], columns=mid_cols)
        p_e = float(model_early.predict_proba(x_e)[0, 1])
        p_m = float(model_midlate.predict_proba(x_m)[0, 1])
        p_e = _apply_calibrator(artifact, p_e, which="early")
        p_m = _apply_calibrator(artifact, p_m, which="midlate")
        clip = artifact.get("early_prob_clip") or [0.02, 0.98]
        p_e = float(np.clip(p_e, float(clip[0]), float(clip[1])))
        w = _blend_weight(
            minute,
            float(artifact.get("blend_start", 6.0)),
            float(artifact.get("blend_end", 10.0)),
        )
        prob_raw = (1 - w) * p_e + w * p_m
        prob = prob_raw
        feats["_prob_early"] = p_e
        feats["_prob_midlate"] = p_m
        feats["_blend_w"] = w
    else:
        columns = artifact.get("feature_columns", [])
        x = pd.DataFrame([[feats.get(col, 0.0) for col in columns]], columns=columns)
        prob_raw = float(artifact["model"].predict_proba(x)[0, 1])
        prob = _apply_calibrator(artifact, prob_raw)
        if artifact.get("use_time_shrinkage", False):
            prob = _apply_time_shrinkage(prob, minute)

    guard_on = bool(artifact.get("use_gold_guard", True))
    prob, guard_meta = apply_gold_consistency_guard(prob, feats, enabled=guard_on, minute=minute)
    feats["_gold_guard_applied"] = float(guard_meta["gold_guard_applied"])
    feats["_p_gold"] = float(guard_meta["p_gold"])
    feats["_gold_guard_alpha"] = float(guard_meta["gold_guard_alpha"])

    conf = prediction_confidence(minute, prob, artifact)
    feats["_prob_raw"] = float(prob_raw)
    feats["_low_confidence"] = float(conf["low_confidence"])
    feats["_confidence"] = conf["confidence"]
    return float(np.clip(prob, 0.02, 0.98)), feats, builder.explain(snap, feats)


def detect_turning_points(
    timeline: pd.DataFrame,
    events: list[dict[str, Any]] | None = None,
    *,
    delta_threshold: float = 0.08,
) -> list[dict[str, Any]]:
    """Detect win-prob swings and align nearby objective events."""
    if timeline is None or timeline.empty:
        return []
    df = timeline.copy()
    prob_col = "prob" if "prob" in df.columns else ("camp1_win_prob" if "camp1_win_prob" in df.columns else ("prob_camp1" if "prob_camp1" in df.columns else None))
    minute_col = "minute" if "minute" in df.columns else ("minute_bin" if "minute_bin" in df.columns else None)
    if not prob_col or not minute_col:
        return []
    df = df.sort_values(minute_col).reset_index(drop=True)
    df["_prob"] = pd.to_numeric(df[prob_col], errors="coerce")
    df["_minute"] = pd.to_numeric(df[minute_col], errors="coerce")
    df = df.dropna(subset=["_prob", "_minute"])
    turns: list[dict[str, Any]] = []
    events = events or []
    for i in range(1, len(df)):
        prev_p = float(df.loc[i - 1, "_prob"])
        cur_p = float(df.loc[i, "_prob"])
        delta = cur_p - prev_p
        minute = float(df.loc[i, "_minute"])
        related = []
        for ev in events:
            ev_m = float(ev.get("minute", 0) or 0)
            if abs(ev_m - minute) <= 1.2:
                related.append(ev.get("label", ev.get("type", "")))
        if abs(delta) >= delta_threshold or related:
            turns.append(
                {
                    "minute": minute,
                    "delta": round(delta, 4),
                    "prob_before": round(prev_p, 4),
                    "prob_after": round(cur_p, 4),
                    "direction": "camp1" if delta > 0 else "camp2",
                    "label": f"{'上升' if delta > 0 else '下降'} {abs(delta):.0%}",
                    "events": related[:3],
                }
            )
    # de-dupe close minutes
    cleaned: list[dict[str, Any]] = []
    for t in turns:
        if cleaned and abs(cleaned[-1]["minute"] - t["minute"]) < 0.8:
            if abs(t["delta"]) > abs(cleaned[-1]["delta"]):
                cleaned[-1] = t
            continue
        cleaned.append(t)
    return cleaned


def generate_battle_report(
    battle: dict[str, Any],
    timeline: pd.DataFrame | None,
    events: list[dict[str, Any]] | None = None,
    turns: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a short Chinese match report for dashboard / interview demo."""
    events = events or []
    turns = turns or []
    c1 = battle.get("camp1") or battle.get("team1") or "Camp1"
    c2 = battle.get("camp2") or battle.get("team2") or "Camp2"
    winner = battle.get("winner") or ""
    win_camp = int(battle.get("win_camp", 0) or 0)
    if not winner and win_camp in (1, 2):
        winner = c1 if win_camp == 1 else c2
    lines = [f"【战报】{c1} vs {c2}"]

    if timeline is not None and not timeline.empty:
        prob_col = "prob" if "prob" in timeline.columns else ("camp1_win_prob" if "camp1_win_prob" in timeline.columns else "prob_camp1")
        minute_col = "minute" if "minute" in timeline.columns else "minute_bin"
        if prob_col in timeline.columns:
            tl = timeline.copy()
            tl[prob_col] = pd.to_numeric(tl[prob_col], errors="coerce")
            tl[minute_col] = pd.to_numeric(tl[minute_col], errors="coerce")
            tl = tl.dropna(subset=[prob_col, minute_col]).sort_values(minute_col)
            if not tl.empty:
                early = tl[tl[minute_col] <= 5]
                if not early.empty:
                    p0 = float(early.iloc[0][prob_col])
                    lean = c1 if p0 >= 0.55 else (c2 if p0 <= 0.45 else "双方均衡")
                    lines.append(f"开局：模型倾向 {lean}（约 {p0:.0%}）。")
                if "gold_diff" in tl.columns:
                    gd = pd.to_numeric(tl["gold_diff"], errors="coerce").dropna()
                    if not gd.empty:
                        lines.append(f"经济：最大领先 {gd.max():+.0f}，最大落后 {gd.min():+.0f}。")
                late = tl[tl[minute_col] >= 8]
                low_conf = 0
                if "_low_confidence" in tl.columns:
                    low_conf = int(pd.to_numeric(tl["_low_confidence"], errors="coerce").fillna(0).sum())
                elif "low_confidence" in tl.columns:
                    low_conf = int(tl["low_confidence"].astype(bool).sum())
                if low_conf:
                    lines.append(f"置信：有 {low_conf} 个切片标记为低置信，解说请谨慎引用绝对值。")

    if turns:
        top = sorted(turns, key=lambda x: abs(x.get("delta", 0)), reverse=True)[:3]
        bits = []
        for t in top:
            who = c1 if t.get("direction") == "camp1" else c2
            ev = "；".join(t.get("events") or [])
            bits.append(f"{t['minute']:.0f}分钟胜率向{who}摆动{abs(t.get('delta', 0)):.0%}" + (f"（{ev}）" if ev else ""))
        lines.append("关键拐点：" + "；".join(bits) + "。")
    elif events:
        heavy = sorted(events, key=lambda e: e.get("weight", 0), reverse=True)[:3]
        lines.append("关键事件：" + "；".join(f"{e.get('minute', '?')}分 {e.get('label', e.get('type'))}" for e in heavy) + "。")

    if winner:
        lines.append(f"终局：{winner} 获胜。")
    else:
        lines.append("终局：胜负未知。")
    return "\n".join(lines)


# ---------------- P18 · 赛后教练简报（规则版） ----------------

def load_analysis_table(name: str) -> pd.DataFrame:
    """读取 ``data/analysis/{name}.csv``（matches / battles / teams / events）；缺失或损坏返回空表。"""
    path = PROJECT_ROOT / "data" / "analysis" / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.ParserError):
        return pd.DataFrame()


def _fmt_signed_cn(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if f != f:
        return "—"
    return f"{f:+,.0f}"


def _fmt_min_cn(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if f != f:
        return "—"
    return f"{f:.1f}′"


def build_postmatch_brief(match_id: str) -> dict[str, Any]:
    """P18 · 赛后教练简报（规则版，无 LLM）：Markdown + meta。

    P0 范围：结果与结论三句话、单局结果表、关键转折点、BP 与阵容、
    资源与经济、选手要点、数据附录；舆情章节无数据时跳过（不生成占位情绪）。
    数字全部来自本地数据（快照 / 分析表 / 模型产物），带来源标签与模型版本。
    """
    matches = load_analysis_table("matches")
    battles = load_analysis_table("battles")
    if matches.empty or "match_id" not in matches.columns:
        return {"state": "empty", "message": "analysis/matches.csv 为空，请先运行 -m kpl_insight.datasets.build"}
    m = matches[matches["match_id"].astype(str) == str(match_id)]
    if m.empty:
        return {"state": "empty", "message": f"未找到大场 {match_id}"}
    m = m.iloc[0]
    team1, team2 = str(m.get("team1") or ""), str(m.get("team2") or "")
    date, stage = str(m.get("date") or ""), str(m.get("stage") or "未知赛段")

    b_sub = battles[battles["match_id"].astype(str) == str(match_id)].copy() if not battles.empty else pd.DataFrame()
    if not b_sub.empty:
        b_sub = b_sub.sort_values("game_no")
    wins1 = int((b_sub["winner"] == team1).sum()) if not b_sub.empty else 0
    wins2 = int((b_sub["winner"] == team2).sum()) if not b_sub.empty else 0

    artifact = load_model() or {}
    train_status = _read_json_file(REALTIME_DIR / "train_status.json") or {}
    model_ver = str(artifact.get("version") or train_status.get("version") or "—")
    model_name = str(artifact.get("model_name") or train_status.get("model_name") or "—")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    games: list[dict[str, Any]] = []
    for _, r in b_sub.iterrows():
        bid = str(r.get("battle_id"))
        snaps = load_battle_jsons(RAW_DIR / bid) if (RAW_DIR / bid).exists() else []
        win_camp = 1 if (str(r.get("winner") or "") == team1) else 2 if (str(r.get("winner") or "") == team2) else 0
        swing = classify_battle_swing(snaps, win_camp) if (snaps and win_camp) else {}
        games.append(
            {
                "battle_id": bid,
                "game_no": int(r.get("game_no") or len(games) + 1),
                "winner": str(r.get("winner") or ""),
                "team1": str(r.get("team1") or ""),
                "team2": str(r.get("team2") or ""),
                "duration_min": r.get("duration_min"),
                "gold_diff": r.get("gold_diff"),
                "kill_diff": r.get("kill_diff"),
                "tower_diff": r.get("tower_diff"),
                "objective_diff": r.get("objective_diff"),
                "has_timeline": bool(r.get("has_timeline")),
                "snapshot_count": r.get("snapshot_count"),
                "comeback": bool(swing.get("comeback")),
                "snaps": snaps,
            }
        )

    key = None
    if games:
        pool = [g for g in games if g["has_timeline"]] or games
        comeback_pool = [g for g in pool if g["comeback"]]
        key = max(comeback_pool or pool, key=lambda g: float(g["duration_min"] or 0))

    tl = _replay_v11_timeline(key["battle_id"]).reset_index(drop=True) if key else pd.DataFrame()
    events = detect_events(key["snaps"]) if (key and key["snaps"]) else []
    turns = detect_turning_points(tl, events) if (key and not tl.empty) else []
    bp = load_battle_bp(key["battle_id"]) if key else {}
    players = (load_battle_players(key["battle_id"]).get("players") or []) if key else []
    key_no = key["game_no"] if key else "—"

    lines: list[str] = []
    lines.append(f"# 赛后教练简报 · {team1} vs {team2}")
    lines.append("")
    lines.append(f"> 生成时间：{generated_at} · 大场 `{match_id}` · 模型：{model_ver}（{model_name}）")
    lines.append("> 口径：事件 / 经济 / BP / 选手为「官方」字段；胜率类为「估算」（V11 校准）。")
    lines.append("")

    lines.append("## 1. 结果与结论")
    lines.append("")
    lines.append(f"- **{date} · {stage} · 大场比分 {wins1} : {wins2}**")
    if key:
        k_tag = "（翻盘局）" if key["comeback"] else ""
        lines.append(
            f"- 关键局：第 {key_no} 局，时长 {_fmt_min_cn(key['duration_min'])}{k_tag}，"
            f"终局金差 {_fmt_signed_cn(key['gold_diff'])}（{key['team1']} 为正）。"
        )
    swing_line = "胜率曲线波动：—"
    if not tl.empty and len(tl) >= 2:
        probs = pd.to_numeric(tl["camp1_win_prob"], errors="coerce")
        diffs = probs.diff().abs()
        if diffs.notna().any():
            idx = int(diffs.idxmax())
            direction = "蓝方" if float(probs.loc[idx]) >= float(probs.loc[idx - 1]) else "红方"
            swing_line = (
                f"胜率曲线最大摆动在第 {float(tl.loc[idx, 'minute']):.0f}′"
                f"（{direction} +{float(diffs.loc[idx]):.0%}），对应当刻金差 {_fmt_signed_cn(tl.loc[idx, 'gold_diff'])}"
            )
    lines.append(f"- {swing_line}（估算 · V11）。")
    lines.append("- 舆情焦点：暂无数据（P15 待建），本节跳过，不生成占位情绪数字。")
    lines.append("")

    lines.append("## 2. 单局结果（官方）")
    lines.append("")
    lines.append("> 差值口径：均为该局蓝方（camp1）为正。")
    lines.append("")
    lines.append("| 局 | 蓝方 | 胜方 | 时长 | 金差 | 击杀差 | 推塔差 | 资源差 | 数据 |")
    lines.append("|----|------|------|------|------|--------|--------|--------|------|")
    for g in games:
        data_tag = "CLEAN" if g["has_timeline"] else f"回补帧（{int(g['snapshot_count'] or 0)} 切片）"
        lines.append(
            f"| 第 {g['game_no']} 局 | {g['team1'] or '—'} | {g['winner'] or '—'} | {_fmt_min_cn(g['duration_min'])} | "
            f"{_fmt_signed_cn(g['gold_diff'])} | {_fmt_signed_cn(g['kill_diff'])} | "
            f"{_fmt_signed_cn(g['tower_diff'])} | {_fmt_signed_cn(g['objective_diff'])} | {data_tag} |"
        )
    lines.append("")

    lines.append(f"## 3. 关键转折点（第 {key_no} 局 · 估算）")
    lines.append("")
    if turns:
        top_turns = sorted(turns, key=lambda t: abs(float(t.get("delta") or 0)), reverse=True)[:5]
        for t in top_turns:
            ev_txt = "、".join((t.get("events") or [])[:3])
            ev_suffix = f" · {ev_txt}" if ev_txt else ""
            lines.append(
                f"- {float(t.get('minute') or 0):.0f}′ · 胜率 {t.get('label')}"
                f"（{float(t.get('prob_before') or 0):.0%} → {float(t.get('prob_after') or 0):.0%}）{ev_suffix}"
            )
    else:
        lines.append("- 无转折点数据（快照不足或时间线为空）。")
    lines.append("")

    lines.append(f"## 4. BP 与阵容（官方 · 第 {key_no} 局）")
    lines.append("")
    steps = (bp.get("steps") or []) if bp else []
    if steps:
        for camp, camp_name in ((1, bp.get("camp1_team") or team1), (2, bp.get("camp2_team") or team2)):
            picks = [s["hero_name"] for s in steps if s.get("action") == "pick" and int(s.get("camp") or 0) == camp]
            bans = [s["hero_name"] for s in steps if s.get("action") == "ban" and int(s.get("camp") or 0) == camp]
            lines.append(f"- **{camp_name}**：pick {' / '.join(picks) or '—'}；ban {' / '.join(bans) or '—'}")
        if bp.get("incomplete"):
            lines.append("- ⚠️ BP 列表不完整（非 20 步）。")
    else:
        lines.append("- 无 BP 数据。")
    lines.append("")

    lines.append(f"## 5. 资源与经济（官方 · 第 {key_no} 局）")
    lines.append("")
    if key:
        lines.append(
            f"- 终局：金差 {_fmt_signed_cn(key['gold_diff'])} · 击杀差 {_fmt_signed_cn(key['kill_diff'])} · "
            f"推塔差 {_fmt_signed_cn(key['tower_diff'])} · 资源差 {_fmt_signed_cn(key['objective_diff'])}"
            f"（蓝方 {key['team1']} 为正）"
        )
    if players:
        by_pos: dict[str, dict[int, float]] = {}
        for p in players:
            by_pos.setdefault(str(p.get("position_name") or "—"), {})[int(p.get("camp") or 0)] = float(p.get("gold") or 0)
        pairs = [(pos, d[1] - d[2]) for pos, d in by_pos.items() if 1 in d and 2 in d]
        pairs.sort(key=lambda x: -abs(x[1]))
        if pairs and key:
            lines.append(
                f"- 分路经济对位（{key['team1']} − {key['team2']}）："
                + "；".join(f"{pos} {_fmt_signed_cn(d)}" for pos, d in pairs[:3])
            )
    lines.append("")

    lines.append(f"## 6. 选手要点（官方 · 第 {key_no} 局）")
    lines.append("")
    if players:
        lines.append("| 阵营 | 选手 | 英雄 | 分路 | KDA | 经济 | 参团 | 输出占比 |")
        lines.append("|------|------|------|------|-----|------|------|----------|")
        for camp in (1, 2):
            side = [p for p in players if int(p.get("camp") or 0) == camp]
            side.sort(key=lambda p: -float(p.get("mvp_score") or 0))
            for p in side[:3]:
                mvp = " · MVP" if p.get("is_mvp") else ""
                hurt = p.get("hurt_to_hero_total_rate")
                part = p.get("participation_rate")
                hurt_txt = f"{float(hurt):.1%}" if hurt is not None else "—"
                part_txt = f"{float(part):.0f}%" if part is not None else "—"
                lines.append(
                    f"| {p.get('camp_name') or camp} | {p.get('player_name')}{mvp} | {p.get('hero_name')} | "
                    f"{p.get('position_name') or '—'} | {p.get('kda_text') or '—'} | "
                    f"{int(p.get('gold') or 0):,} | {part_txt} | {hurt_txt} |"
                )
    else:
        lines.append("- 无选手面板数据。")
    lines.append("")

    lines.append("## 7. 舆情与弹幕")
    lines.append("")
    lines.append("无数据（P15 待建），已跳过。")
    lines.append("")

    lines.append("## 8. 数据附录与来源")
    lines.append("")
    lines.append(f"- 模型：{model_ver}（{model_name}）；训练时间 {train_status.get('trained_at') or '—'}")
    _hb = train_status.get("holdout_real_brier")
    _he = train_status.get("holdout_early_brier")
    lines.append(
        "- holdout（clean 真实局）：Brier(全) "
        + (f"{float(_hb):.4f}" if _hb is not None else "—")
        + " · early "
        + (f"{float(_he):.4f}" if _he is not None else "—")
    )
    lines.append(
        "- 快照范围："
        + "；".join(f"第 {g['game_no']} 局 `{g['battle_id']}`（{int(g['snapshot_count'] or 0)} 切片）" for g in games)
    )
    lines.append("- 口径与术语：`docs/getting-started.md`；生成器：`kpl_insight.core.build_postmatch_brief`（规则版，无 LLM）")
    md = "\n".join(lines) + "\n"

    meta = {
        "match_id": str(match_id),
        "generated_at": generated_at,
        "model_version": model_ver,
        "model_name": model_name,
        "trained_at": train_status.get("trained_at"),
        "key_battle": key["battle_id"] if key else None,
        "battles": [g["battle_id"] for g in games],
        "chapters_enabled": ["结果与结论", "单局结果", "关键转折点", "BP与阵容", "资源与经济", "选手要点", "数据附录"],
        "chapters_skipped": ["舆情与弹幕（P15 无数据）"],
    }
    return {"state": "ok", "markdown": md, "meta": meta}


# ---------------- P13 · 高光赛季之最（规则版） ----------------

HONORS_RULES_VERSION = "v1"
HONOR_TIE_EPS_RATE = 0.005
HONOR_MIN_TEAM_MATCHES = 8
HONOR_MIN_TEAM_BATTLES = 10
HONOR_MIN_TEAM_STREAK_MATCHES = 5
HONOR_MIN_PLAYER_GAMES = 10
HONOR_MIN_HERO_PICKS = 15
HONOR_MIN_HERO_BAN = 5

_LANE_RULE_CODE = {"对抗路": "TOP", "打野": "JGL", "中路": "MID", "发育路": "ADC", "游走": "SUP"}


def _players_source_table() -> pd.DataFrame:
    """读取 ``data/processed/players.csv``（选手面板数据源）；缺失或损坏返回空表。"""
    path = PROJECT_ROOT / "data" / "processed" / "players.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.ParserError):
        return pd.DataFrame()


def _tie_top(entries: list[dict[str, Any]], eps: float) -> list[dict[str, Any]]:
    """并列第一名：按 ``key`` 降序，返回与第一名差值 ≤ eps 的全部条目（稳定顺序）。"""
    if not entries:
        return []
    ordered = sorted(entries, key=lambda e: -float(e["key"]))
    top_key = float(ordered[0]["key"])
    picked = [e for e in ordered if abs(float(e["key"]) - top_key) <= eps]
    for e in picked:
        e.pop("key", None)
    return picked


def _honor_card(
    rule_id: str,
    title: str,
    category: str,
    winners: list[dict[str, Any]],
    rule_summary: str,
    n_label: str,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "title": title,
        "category": category,
        "source_tag": "自算荣誉",
        "rule_summary": rule_summary,
        "n_label": n_label,
        "tie": len(winners) > 1,
        "entries": winners,
    }


def build_season_honors() -> dict[str, Any]:
    """P13 · 高光赛季之最（P0 规则引擎）：预设之最 + 最小样本 + 并列全展示。

    来源标签固定「自算荣誉」（非官方评选）；胜率类采用稳健排序（Wilson 95% 下界）。
    同一数据快照下可复算（无随机性）；规则版本见 ``HONORS_RULES_VERSION``。
    """
    battles = load_analysis_table("battles")
    teams_tbl = load_analysis_table("teams")
    if battles.empty or teams_tbl.empty:
        return {"state": "empty", "message": "analysis 表为空，请先运行 -m kpl_insight.datasets.build"}

    cards: list[dict[str, Any]] = []
    eps = HONOR_TIE_EPS_RATE
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        year = pd.to_datetime(battles["date"], errors="coerce").dt.year.dropna().max()
        season_label = f"{int(year)} 赛季" if pd.notna(year) else "赛季"
    except Exception:
        season_label = "赛季"

    # ---------- 战队：大场结果（单局胜数多者胜，平局跳过） ----------
    mt = _team_match_records(battles)
    if not mt.empty:
        agg = mt.groupby("team").agg(matches=("win", "count"), wins=("win", "sum")).reset_index()
        agg = agg[agg["matches"] >= HONOR_MIN_TEAM_MATCHES].copy()
        if not agg.empty:
            agg["wr"] = agg["wins"] / agg["matches"]
            ci = [wilson_ci(int(w), int(n)) for w, n in zip(agg["wins"], agg["matches"])]
            entries = [
                {
                    "name": str(r["team"]),
                    "key": ci[i][0],
                    "value_text": f"{r['wr']:.1%}",
                    "detail": f"Wilson 下界 {ci[i][0]:.1%} · {int(r['wins'])}W{int(r['matches'] - r['wins'])}L",
                    "n": int(r["matches"]),
                }
                for i, (_, r) in enumerate(agg.reset_index(drop=True).iterrows())
            ]
            cards.append(_honor_card(
                "HONOR_TEAM_WR", "最高胜率战队", "战队", _tie_top(entries, eps),
                f"大场胜率，稳健排序（Wilson 95% 下界）；最小 n={HONOR_MIN_TEAM_MATCHES} 大场；并列 ε≤0.5pct",
                "大场",
            ))

        mr = mt.sort_values(["team", "date", "match_id"])

        def _max_streak(ws: pd.Series) -> int:
            best = cur = 0
            for w in ws:
                cur = cur + 1 if w else 0
                best = max(best, cur)
            return best

        streaks = mr.groupby("team").agg(streak=("win", _max_streak), matches=("win", "count")).reset_index()
        streaks = streaks[streaks["matches"] >= HONOR_MIN_TEAM_STREAK_MATCHES]
        if not streaks.empty:
            entries = [
                {
                    "name": str(r["team"]),
                    "key": int(r["streak"]),
                    "value_text": f"{int(r['streak'])} 连胜",
                    "detail": f"{int(r['matches'])} 场大场样本",
                    "n": int(r["matches"]),
                }
                for _, r in streaks.iterrows() if int(r["streak"]) > 0
            ]
            cards.append(_honor_card(
                "HONOR_TEAM_STREAK", "最长连胜", "战队", _tie_top(entries, 0.0),
                f"大场连胜（按日期序，平局大场跳过）；最小 n={HONOR_MIN_TEAM_STREAK_MATCHES} 大场；并列取同值",
                "大场",
            ))

    # ---------- 战队：场均经济差（单局视角） ----------
    t = teams_tbl.copy()
    t["gold_diff"] = pd.to_numeric(t["gold_diff"], errors="coerce")
    tg = t.groupby("team").agg(n=("gold_diff", "count"), mean=("gold_diff", "mean")).reset_index()
    tg = tg[tg["n"] >= HONOR_MIN_TEAM_BATTLES]
    if not tg.empty:
        entries = [
            {
                "name": str(r["team"]),
                "key": r["mean"],
                "value_text": f"{r['mean']:+,.0f}",
                "detail": f"终局金差均值（队视角）· {int(r['n'])} 单局",
                "n": int(r["n"]),
            }
            for _, r in tg.iterrows()
        ]
        cards.append(_honor_card(
            "HONOR_TEAM_GOLD", "场均经济差最高", "战队", _tie_top(entries, 0.5),
            f"终局金差均值（队视角）；最小 n={HONOR_MIN_TEAM_BATTLES} 单局；并列 ε≤0.5 金",
            "单局",
        ))

    # ---------- 选手（分位置，最小 n=10 局） ----------
    players = _players_source_table()
    if not players.empty and "position_desc" in players.columns:
        p = players.copy()
        p["player_name"] = p["player_name"].astype(str)
        for col in ("mvp_score", "participation_rate", "hurt_to_hero_total_rate"):
            p[col] = pd.to_numeric(p.get(col, 0), errors="coerce")
        p["is_mvp"] = pd.to_numeric(p.get("is_mvp", 0), errors="coerce").fillna(0).astype(int)

        for lane, code in _LANE_RULE_CODE.items():
            g = (
                p[p["position_desc"] == lane]
                .groupby("player_name")
                .agg(n=("mvp_score", "count"), score=("mvp_score", "mean"), team=("team_name", "first"))
                .reset_index()
            )
            g = g[g["n"] >= HONOR_MIN_PLAYER_GAMES]
            if g.empty:
                continue
            entries = [
                {
                    "name": f"{r['player_name']} · {r['team']}",
                    "key": r["score"],
                    "value_text": f"{r['score']:.2f}",
                    "detail": f"mvp_score 均值 · {int(r['n'])} 局",
                    "n": int(r["n"]),
                }
                for _, r in g.iterrows()
            ]
            cards.append(_honor_card(
                f"HONOR_PLAYER_SCORE_{code}", f"{lane} · 位置之最（综合分）", "选手",
                _tie_top(entries, 0.005),
                f"{lane} 选手 mvp_score 均值；最小 n={HONOR_MIN_PLAYER_GAMES} 局；并列 ε≤0.005",
                "局",
            ))

        gm = (
            p.groupby("player_name")
            .agg(n=("is_mvp", "count"), mvp=("is_mvp", "sum"), team=("team_name", "first"))
            .reset_index()
        )
        gm = gm[gm["n"] >= HONOR_MIN_PLAYER_GAMES]
        if not gm.empty:
            entries = [
                {
                    "name": f"{r['player_name']} · {r['team']}",
                    "key": int(r["mvp"]),
                    "value_text": f"{int(r['mvp'])} 次",
                    "detail": f"MVP 率 {r['mvp'] / r['n']:.0%} · {int(r['n'])} 局",
                    "n": int(r["n"]),
                }
                for _, r in gm.iterrows()
            ]
            cards.append(_honor_card(
                "HONOR_PLAYER_MVP", "MVP 次数最多（全局）", "选手", _tie_top(entries, 0.0),
                f"is_mvp 求和；最小 n={HONOR_MIN_PLAYER_GAMES} 局；MVP 为全局评选，不分位置；并列取同值",
                "局",
            ))

        for lane in ("中路", "发育路"):
            g = (
                p[p["position_desc"] == lane]
                .groupby("player_name")
                .agg(n=("hurt_to_hero_total_rate", "count"), dmg=("hurt_to_hero_total_rate", "mean"), team=("team_name", "first"))
                .reset_index()
            )
            g = g[g["n"] >= HONOR_MIN_PLAYER_GAMES]
            if g.empty:
                continue
            entries = [
                {
                    "name": f"{r['player_name']} · {r['team']}",
                    "key": r["dmg"],
                    "value_text": f"{r['dmg']:.1%}",
                    "detail": f"输出占比均值 · {int(r['n'])} 局",
                    "n": int(r["n"]),
                }
                for _, r in g.iterrows()
            ]
            cards.append(_honor_card(
                f"HONOR_PLAYER_DMG_{_LANE_RULE_CODE[lane]}", f"{lane} · 输出占比最高", "选手",
                _tie_top(entries, eps),
                f"{lane} 选手 hurt_to_hero_total_rate 均值；仅中路/发育路；最小 n={HONOR_MIN_PLAYER_GAMES} 局；并列 ε≤0.5pct",
                "局",
            ))

    # ---------- 英雄（基于 BP 归档） ----------
    meta = aggregate_bp_meta()
    hero_meta = meta.get("heroes") or {}
    h_rows = [
        {
            "英雄": str(name),
            "picks": int((h.get("pick") or {}).get("k") or 0),
            "pick_rate": float((h.get("pick") or {}).get("rate") or 0),
            "ban_rate": float((h.get("ban") or {}).get("rate") or 0),
            "ban_n": int((h.get("ban") or {}).get("k") or 0),
            "wr": float((h.get("win") or {}).get("rate") or 0),
            "wr_lo": float((h.get("win") or {}).get("ci_low") or 0),
            "wr_n": int((h.get("win") or {}).get("n") or 0),
        }
        for name, h in hero_meta.items()
    ]
    if h_rows:
        cand = [r for r in h_rows if r["picks"] >= HONOR_MIN_HERO_PICKS]
        if cand:
            entries = [
                {
                    "name": r["英雄"], "key": r["wr_lo"], "value_text": f"{r['wr']:.1%}",
                    "detail": f"Wilson 下界 {r['wr_lo']:.1%} · {r['picks']} 次出场", "n": r["wr_n"],
                }
                for r in cand
            ]
            cards.append(_honor_card(
                "HONOR_HERO_WR", "胜率最高英雄", "英雄", _tie_top(entries, eps),
                f"出场胜率，稳健排序（Wilson 95% 下界）；最小 n={HONOR_MIN_HERO_PICKS} 次出场；并列 ε≤0.5pct",
                "出场",
            ))
        cand = [r for r in h_rows if r["picks"] >= HONOR_MIN_HERO_BAN]
        if cand:
            entries = [
                {
                    "name": r["英雄"], "key": r["pick_rate"], "value_text": f"{r['pick_rate']:.1%}",
                    "detail": f"{r['picks']} 次出场", "n": r["picks"],
                }
                for r in cand
            ]
            cards.append(_honor_card(
                "HONOR_HERO_PICK", "登场率最高英雄", "英雄", _tie_top(entries, eps),
                f"pick 率（出场 ÷ 归档对局）；最小 n={HONOR_MIN_HERO_BAN} 次出场；并列 ε≤0.5pct",
                "出场",
            ))
        cand = [r for r in h_rows if r["ban_n"] >= HONOR_MIN_HERO_BAN]
        if cand:
            entries = [
                {
                    "name": r["英雄"], "key": r["ban_rate"], "value_text": f"{r['ban_rate']:.1%}",
                    "detail": f"被 ban {r['ban_n']} 次", "n": r["ban_n"],
                }
                for r in cand
            ]
            cards.append(_honor_card(
                "HONOR_HERO_BAN", "Ban 率最高英雄", "英雄", _tie_top(entries, eps),
                f"ban 率（被 ban ÷ 归档对局）；最小 n={HONOR_MIN_HERO_BAN} 次被 ban；并列 ε≤0.5pct",
                "局",
            ))

    copy_texts = []
    for c in cards:
        parts = "、".join(f"{e['name']}（{e['value_text']}）" for e in c["entries"])
        ns = " / ".join(str(e["n"]) for e in c["entries"])
        copy_texts.append(
            f"【{season_label}·{c['title']}】{parts}（样本 n={ns}）\n"
            f"口径：{c['rule_summary']}（规则ID {c['rule_id']} {HONORS_RULES_VERSION}）\n"
            f"数据源：{c['source_tag']}；生成时间 {generated_at}\n"
            f"注：非官方评选，转载请附口径。"
        )

    return {
        "state": "ok",
        "version": HONORS_RULES_VERSION,
        "season_label": season_label,
        "generated_at": generated_at,
        "cards": cards,
        "copy_texts": copy_texts,
    }


# ---------------- P12 · 单局阶段切片与归因卡 ----------------

_PHASES: list[tuple[str, str, float, float]] = [
    ("early", "早期 (≤8′)", 0.0, 8.0),
    ("mid", "中期 (9–15′)", 8.0, 15.0),
    ("late", "后期 (16′+)", 15.0, 1e9),
]
_P12_MIN_SWING = 0.05


def _snapshot_objectives(s: dict[str, Any], camp: int) -> int:
    return sum(int(s.get(f"camp{camp}_{key}", 0) or 0) for key in ("tyrant", "dark_tyrant", "lord", "storm"))


def build_phase_attribution(battle_id: str) -> dict[str, Any]:
    """P12 · 单局阶段切片 + 归因卡（描述性 / 叙事因子分层，措辞合规）。

    阶段切片：≤8′ / 9–15′ / 16′+ 三段，各段期末差值与段内变化（官方字段差分）。
    归因卡：胜率摆动 / 资源转折 / 分路失衡（标签「描述性」，措辞用「伴随」，禁因果断言）。
    叙事因子：V11 FeatureBuilder.explain（标签「叙事因子（非权重）」，禁止按模型权重引用）。
    """
    battle_id = str(battle_id or "").strip()
    battle_dir = RAW_DIR / battle_id
    snaps = load_battle_jsons(battle_dir) if battle_dir.exists() else []
    if not snaps:
        return {"state": "empty", "message": "该对局没有本地快照"}
    snaps = sorted(snaps, key=lambda s: float(s.get("minute", 0) or 0))
    win_camp = 0
    for s in reversed(snaps):
        if int(s.get("win_camp", 0) or 0) in (1, 2):
            win_camp = int(s["win_camp"])
            break

    rows = [
        {
            "minute": float(s.get("minute", 0) or 0),
            "gd": float(s.get("camp1_gold", 0) or 0) - float(s.get("camp2_gold", 0) or 0),
            "kd": float(s.get("camp1_kill", 0) or 0) - float(s.get("camp2_kill", 0) or 0),
            "td": float(s.get("camp1_tower", 0) or 0) - float(s.get("camp2_tower", 0) or 0),
            "rd": float(_snapshot_objectives(s, 1) - _snapshot_objectives(s, 2)),
        }
        for s in snaps
    ]
    df = pd.DataFrame(rows)
    tl = _replay_v11_timeline(battle_id)
    if not tl.empty:
        tl = tl.copy()
        tl["minute_num"] = pd.to_numeric(tl["minute"], errors="coerce")
        tl["camp1_win_prob"] = pd.to_numeric(tl["camp1_win_prob"], errors="coerce")

    phases: list[dict[str, Any]] = []
    prev_end = {"gd": 0.0, "kd": 0.0, "td": 0.0, "rd": 0.0}
    for code, label, lo, hi in _PHASES:
        sub = df[(df["minute"] > lo) & (df["minute"] <= hi)] if lo > 0 else df[df["minute"] <= hi]
        if sub.empty:
            continue
        last = sub.iloc[-1]
        prob_mean = None
        if not tl.empty:
            m2 = tl[(tl["minute_num"] > lo) & (tl["minute_num"] <= hi)]
            if not m2.empty and m2["camp1_win_prob"].notna().any():
                prob_mean = float(m2["camp1_win_prob"].mean())
        phases.append({
            "code": code,
            "label": label,
            "last_minute": float(last["minute"]),
            "n": int(len(sub)),
            "end": {k: float(last[k]) for k in ("gd", "kd", "td", "rd")},
            "delta": {k: float(last[k]) - prev_end[k] for k in ("gd", "kd", "td", "rd")},
            "prob_mean": prob_mean,
        })
        for k in ("gd", "kd", "td", "rd"):
            prev_end[k] = float(last[k])

    events = detect_events(snaps)
    cards: list[dict[str, Any]] = []

    if not tl.empty and tl["camp1_win_prob"].notna().sum() >= 2:
        probs = tl["camp1_win_prob"].ffill().bfill()
        diffs = probs.diff().abs()
        if diffs.notna().any():
            idx = int(diffs.idxmax())
            minute = float(tl["minute_num"].iloc[idx])
            direction = "蓝方" if float(probs.iloc[idx]) >= float(probs.iloc[idx - 1]) else "红方"
            near = [e for e in events if abs(float(e.get("minute", 0) or 0) - minute) <= 1.5]
            cards.append({
                "title": "胜率摆动拐点",
                "value": f"{float(diffs.iloc[idx]):.0%}",
                "headline": f"第 {minute:.0f}′ · {direction}走强（{float(probs.iloc[idx - 1]):.0%} → {float(probs.iloc[idx]):.0%}，估算·V11）",
                "note": "伴随事件：" + ("、".join(str(e.get("label")) for e in near[:3]) if near else "无（快照间隔内）"),
                "source": "估算",
            })

    if len(df) >= 2:
        drd = df["rd"].diff().abs()
        if drd.notna().any():
            j = int(drd.idxmax())
            minute = float(df["minute"].iloc[j])
            before, after = float(df["rd"].iloc[j - 1]), float(df["rd"].iloc[j])
            near = [
                e for e in events
                if abs(float(e.get("minute", 0) or 0) - minute) <= 1.5
                and str(e.get("type")) in ("tyrant", "dark_tyrant", "lord", "storm", "big_dragon")
            ]
            cards.append({
                "title": "资源转折",
                "value": f"{after - before:+.0f}",
                "headline": f"第 {minute:.0f}′ 资源差 {before:+.0f} → {after:+.0f}（蓝方为正）",
                "note": "伴随事件：" + ("、".join(str(e.get("label")) for e in near[:3]) if near else "—"),
                "source": "官方",
            })

    players = (load_battle_players(battle_id).get("players") or [])
    if players:
        by_pos: dict[str, dict[int, float]] = {}
        for p in players:
            by_pos.setdefault(str(p.get("position_name") or "—"), {})[int(p.get("camp") or 0)] = float(p.get("gold") or 0)
        pairs = [(pos, d[1] - d[2]) for pos, d in by_pos.items() if 1 in d and 2 in d]
        if pairs:
            pos, diff = max(pairs, key=lambda x: abs(x[1]))
            cards.append({
                "title": "分路失衡（终局）",
                "value": f"{diff:+,.0f}",
                "headline": f"{pos} 经济差最大（蓝方 − 红方）",
                "note": "描述性·伴随现象；未做因果识别，不作追责口径",
                "source": "官方",
            })

    factors: list[dict[str, Any]] = []
    artifact = load_model()
    if artifact is not None and len(snaps) >= 2:
        try:
            _prob, _feats, explain = predict_probability(artifact, snaps[-1], snaps[:-1])
            factors = [
                {
                    "factor": str(e.get("factor") or ""),
                    "leader": str(e.get("leader") or ""),
                    "value": float(e.get("value") or 0),
                    "description": str(e.get("description") or ""),
                }
                for e in (explain or [])[:5]
            ]
        except Exception:
            factors = []

    return {
        "state": "ok",
        "battle_id": battle_id,
        "win_camp": win_camp,
        "phases": phases,
        "cards": cards,
        "factors": factors,
        "note": "阶段切片为官方字段差分（描述性）；叙事因子来自 FeatureBuilder.explain，禁止按模型权重引用（非 SHAP）",
    }


# ---------------- P11 · 英雄池与同位置对位 ----------------

HERO_POOL_STALE_GAMES = 10
MATCHUP_MIN_N = 8


def build_hero_pool(name: str, kind: str = "team") -> dict[str, Any]:
    """P11 · 英雄池：按战队/选手聚合英雄出场、胜率±CI（Wilson）、广度与生疏标记。

    广度：池大小（不重复英雄数）、HHI（份额平方和）、有效英雄数 exp(Shannon)。
    生疏：过去 ≥``HERO_POOL_STALE_GAMES`` 局未再选出即标记。
    胜率仅统计已完赛（winner 已知）的对局。
    """
    players = _players_source_table()
    if players.empty:
        return {"state": "empty", "message": "players.csv 为空，请先运行历史数据集构建"}
    battles = load_analysis_table("battles")
    win_map: dict[str, str] = {}
    if not battles.empty and "winner" in battles.columns:
        for _, r in battles.iterrows():
            w = str(r.get("winner") or "").strip()
            if w:
                win_map[str(r.get("battle_id"))] = w

    p = players.copy()
    if str(kind) == "player":
        p = p[p["player_name"].astype(str) == str(name)]
    else:
        p = p[p["team_name"].astype(str) == str(name)]
    if p.empty:
        return {"state": "empty", "message": f"未找到 {name} 的出场记录"}
    p = p.copy()
    p["_win"] = [
        1 if win_map.get(str(b)) == str(t) else (0 if str(b) in win_map else None)
        for b, t in zip(p["battle_id"], p["team_name"])
    ]
    p["_ts"] = [
        int(str(b).rsplit("_", 1)[-1]) if str(b).rsplit("_", 1)[-1].isdigit() else 0
        for b in p["battle_id"]
    ]
    ts_sorted = sorted(set(int(t) for t in p["_ts"]))

    rows: list[dict[str, Any]] = []
    for hero, g in p.groupby("hero_name"):
        decided = g[g["_win"].notna()]
        n = int(len(decided))
        wins = int(decided["_win"].sum()) if n else 0
        wr = wins / n if n else None
        lo = hi = None
        if n:
            lo, hi = wilson_ci(wins, n)
        last_ts = int(g["_ts"].max())
        stale_games = int(sum(1 for t in ts_sorted if t > last_ts))
        rows.append({
            "hero": str(hero),
            "games": int(len(g)),
            "decided_n": n,
            "wins": wins,
            "wr": wr,
            "ci_low": lo,
            "ci_high": hi,
            "stale_games": stale_games,
            "stale": bool(stale_games >= HERO_POOL_STALE_GAMES),
        })
    rows.sort(key=lambda r: (-r["games"], -(r["wr"] or 0), r["hero"]))
    total_games = len(ts_sorted)
    shares = [r["games"] / sum(x["games"] for x in rows) for r in rows] if rows else []
    hhi = float(sum(s * s for s in shares))
    eff = float(np.exp(-sum(s * np.log(s) for s in shares if s > 0))) if shares else 0.0
    return {
        "state": "ok",
        "name": str(name),
        "kind": str(kind),
        "total_games": total_games,
        "breadth": {"pool_size": len(rows), "hhi": round(hhi, 3), "effective": round(eff, 1)},
        "stale_threshold": HERO_POOL_STALE_GAMES,
        "rows": rows[:40],
    }


def build_hero_matchups(position: str, min_n: int = 4) -> dict[str, Any]:
    """P11 · 同位置对位：同局、同位置、不同战队的英雄（蓝方 vs 红方）历史胜率（Wilson CI）。

    方向定义：蓝方英雄 A 所在阵营的胜场比例；仅统计已完赛对局。
    n < ``MATCHUP_MIN_N`` 的对位标「不足」；文案用「历史对位关联」，不作机制克制断言。
    """
    players = _players_source_table()
    if players.empty or "camp" not in players.columns:
        return {"state": "empty", "message": "players.csv 为空"}
    battles = load_analysis_table("battles")
    win_map: dict[str, str] = {}
    if not battles.empty and "winner" in battles.columns:
        for _, r in battles.iterrows():
            w = str(r.get("winner") or "").strip()
            if w:
                win_map[str(r.get("battle_id"))] = w

    sub = players[players["position_desc"].astype(str) == str(position)]
    pairs: dict[tuple[str, str], list[int]] = {}
    for bid, g in sub.groupby("battle_id"):
        winner = win_map.get(str(bid), "")
        if not winner:
            continue
        c1 = g[g["camp"] == 1]
        c2 = g[g["camp"] == 2]
        if len(c1) != 1 or len(c2) != 1:
            continue
        r1, r2 = c1.iloc[0], c2.iloc[0]
        t1, t2 = str(r1["team_name"]), str(r2["team_name"])
        if t1 == t2:  # 验收：对位 join 不出现同队两人
            continue
        hero_a, hero_b = str(r1["hero_name"]), str(r2["hero_name"])
        if hero_a == hero_b:
            continue
        pairs.setdefault((hero_a, hero_b), []).append(1 if winner == t1 else 0)

    rows = []
    for (a, b), arr in pairs.items():
        n = len(arr)
        wins = sum(arr)
        lo, hi = wilson_ci(wins, n)
        rows.append({
            "hero_blue": a,
            "hero_red": b,
            "n": n,
            "wins": wins,
            "wr": wins / n,
            "ci_low": lo,
            "ci_high": hi,
            "insufficient": n < MATCHUP_MIN_N,
        })
    rows.sort(key=lambda r: (-r["n"], -r["wr"], r["hero_blue"]))
    qualified = [r for r in rows if r["n"] >= int(min_n)]
    return {
        "state": "ok",
        "position": str(position),
        "min_n": int(min_n),
        "insufficient_threshold": MATCHUP_MIN_N,
        "total_pairs": len(rows),
        "rows": qualified[:40],
    }


# ---------------- P16 · 大场胜率模拟器（赛前先验 / 阵容假设） ----------------

SIM_VERSION = "v1"
SIM_MAX_LINEUP = 5


def _team_match_records(battles: pd.DataFrame) -> pd.DataFrame:
    """大场级胜负记录（单局胜数多者胜，平局跳过）：match_id / date / team / win。"""
    rows: list[dict[str, Any]] = []
    if battles.empty:
        return pd.DataFrame(columns=["match_id", "date", "team", "win"])
    b = battles.copy()
    b["winner"] = b["winner"].fillna("").astype(str)
    for mid, g in b.groupby("match_id"):
        t1, t2 = str(g["team1"].iloc[0]), str(g["team2"].iloc[0])
        w1 = int((g["winner"] == t1).sum())
        w2 = int((g["winner"] == t2).sum())
        if w1 == w2:
            continue
        winner = t1 if w1 > w2 else t2
        for team in (t1, t2):
            rows.append({"match_id": mid, "date": str(g["date"].iloc[0]), "team": team, "win": int(team == winner)})
    return pd.DataFrame(rows)


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return float(np.log(p / (1.0 - p)))


def _sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-x)))


def _smoothed_rate(wins: float, n: float, *, prior: float = 0.5, k: float = 4.0) -> float:
    """向先验收缩的平滑胜率（k = 先验强度）。"""
    return (float(wins) + k * prior) / (float(n) + k)


def _series_prob(p: float, best_of: int) -> float:
    """独立同分布下 A 先至 ⌈best_of/2⌉ 胜的概率（解析）。"""
    from math import comb

    m = (int(best_of) + 1) // 2
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return float(sum(comb(m - 1 + k, k) * (p ** m) * ((1 - p) ** k) for k in range(m)))


def _series_score_dist(p: float, best_of: int) -> dict[str, float]:
    """局分概率质量：A 以 m:(m-1+k) 或 B 对称。"""
    from math import comb

    m = (int(best_of) + 1) // 2
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    dist: dict[str, float] = {}
    for k in range(m):
        dist[f"{m}-{k}"] = float(comb(m - 1 + k, k) * (p ** m) * ((1 - p) ** k))
        dist[f"{k}-{m}"] = float(comb(m - 1 + k, k) * ((1 - p) ** m) * (p ** k))
    return dist


def simulate_series(
    team_a: str,
    team_b: str,
    lineup_a: list[str] | None = None,
    lineup_b: list[str] | None = None,
    best_of: int = 5,
) -> dict[str, Any]:
    """P16 · 大场（系列赛）胜率模拟：赛前先验 + 阵容假设 → 单局 p → BO 解析。

    证据合成（logit 空间，权重 = 等效样本 n，封顶 120）：
      ① 战队先验：两队赛季大场胜率（Bradley-Terry 式 logit 差）
      ② 历史交锋：两队直接对局（大场）胜率
      ③ 阵容英雄：双方所选英雄的稳健胜率均值差（按 BP 归档胜率，Wilson 口径的先验收缩）
      ④ 阵容协同：命中历史三人核心组合的平滑胜率差
    系列赛：独立同分布解析（先至 ⌈best_of/2⌉ 胜）；95% 区间由等效样本 SE 传播。
    强假设：不建模局间心理与 BP 学习效应（进阶见 P20）；输出均为「估算」。
    """
    team_a, team_b = str(team_a or "").strip(), str(team_b or "").strip()
    if not team_a or not team_b:
        return {"state": "empty", "message": "请先选择两支战队"}
    if team_a == team_b:
        return {"state": "invalid", "message": "战队 A 与 B 不能相同"}
    best_of = int(best_of) if int(best_of) in (3, 5, 7) else 5

    battles = load_analysis_table("battles")
    if battles.empty:
        return {"state": "empty", "message": "analysis/battles.csv 为空，请先运行 -m kpl_insight.datasets.build"}
    records = _team_match_records(battles)
    if records.empty:
        return {"state": "empty", "message": "无已完赛大场记录"}

    def _team_wr(team: str) -> tuple[float, int]:
        sub = records[records["team"] == team]
        n = int(len(sub))
        return _smoothed_rate(int(sub["win"].sum()), n), n

    wr_a, n_a = _team_wr(team_a)
    wr_b, n_b = _team_wr(team_b)
    if n_a == 0 and n_b == 0:
        return {"state": "empty", "message": f"赛季记录中未找到 {team_a} / {team_b}"}

    signals: list[dict[str, Any]] = []
    warnings: list[str] = []

    # ① 战队先验
    p1 = _sigmoid(_logit(wr_a) - _logit(wr_b))
    w1 = min(n_a + n_b, 120)
    signals.append({
        "signal": "战队先验（赛季大场胜率）",
        "prob_a": p1,
        "n": n_a + n_b,
        "weight": w1,
        "detail": f"{team_a} {wr_a:.1%}（n={n_a}）｜{team_b} {wr_b:.1%}（n={n_b}）",
        "source": "官方",
    })
    if n_a < 8 or n_b < 8:
        warnings.append(f"战队样本偏低（{team_a} n={n_a} / {team_b} n={n_b}），已向 50% 收缩")

    # ② 历史交锋（大场）
    both = records[records["team"].isin([team_a, team_b])]
    h2h = both.groupby("match_id").filter(lambda g: set(g["team"]) == {team_a, team_b})
    if not h2h.empty:
        n_h2h = int(h2h.groupby("match_id").size().shape[0])
        wins_h2h = int(h2h[h2h["team"] == team_a]["win"].sum())
        p2 = _smoothed_rate(wins_h2h, n_h2h, prior=0.5, k=2.0)
        signals.append({
            "signal": "历史交锋（大场）",
            "prob_a": p2,
            "n": n_h2h,
            "weight": float(n_h2h),
            "detail": f"{team_a} {wins_h2h}W{n_h2h - wins_h2h}L",
            "source": "官方",
        })

    # ③ 阵容英雄（需要双方各 ≥3 个英雄）
    lineup_a = [str(h).strip() for h in (lineup_a or []) if str(h).strip()][:SIM_MAX_LINEUP]
    lineup_b = [str(h).strip() for h in (lineup_b or []) if str(h).strip()][:SIM_MAX_LINEUP]
    meta = aggregate_bp_meta()
    heroes_meta = meta.get("heroes") or {}

    def _hero_wr(name: str) -> tuple[float, int]:
        h = (heroes_meta.get(name) or {}).get("win") or {}
        return _smoothed_rate(h.get("k", 0), h.get("n", 0), prior=0.5, k=6.0), int(h.get("n") or 0)

    if len(lineup_a) >= 3 and len(lineup_b) >= 3:
        known_a = [h for h in lineup_a if h in heroes_meta]
        known_b = [h for h in lineup_b if h in heroes_meta]
        if known_a and known_b:
            logits_a = [_logit(_hero_wr(h)[0]) for h in known_a]
            logits_b = [_logit(_hero_wr(h)[0]) for h in known_b]
            p3 = _sigmoid(float(np.mean(logits_a) - np.mean(logits_b)))
            ns = [n for h in known_a + known_b for n in [_hero_wr(h)[1]]]
            n3 = int(min(ns)) if ns else 0
            signals.append({
                "signal": "阵容英雄（稳健胜率均值差）",
                "prob_a": p3,
                "n": n3,
                "weight": float(n3),
                "detail": f"{team_a} 阵容均胜率 {np.mean([_hero_wr(h)[0] for h in known_a]):.1%}｜"
                          f"{team_b} {np.mean([_hero_wr(h)[0] for h in known_b]):.1%}",
                "source": "估算",
            })

        # ④ 阵容协同（命中历史三人核心组合）
        lineup_3 = meta.get("lineup_3") or {}

        def _best_trio(lineup: list[str]) -> tuple[float, int] | None:
            best: tuple[float, int] | None = None
            for key, val in lineup_3.items():
                if set(key) <= set(lineup):
                    n, wins = int(val.get("n", 0)), int(val.get("wins", 0))
                    if n >= 2 and (best is None or n > best[1]):
                        best = (_smoothed_rate(wins, n, prior=0.5, k=3.0), n)
            return best

        trio_a = _best_trio(lineup_a)
        trio_b = _best_trio(lineup_b)
        if trio_a and trio_b:
            p4 = _sigmoid(_logit(trio_a[0]) - _logit(trio_b[0]))
            signals.append({
                "signal": "阵容协同（历史三人核心组合）",
                "prob_a": p4,
                "n": min(trio_a[1], trio_b[1]),
                "weight": float(min(trio_a[1], trio_b[1])),
                "detail": f"{team_a} 核心组 {trio_a[0]:.0%}（n={trio_a[1]}）｜{team_b} {trio_b[0]:.0%}（n={trio_b[1]}）",
                "source": "估算",
            })

    # 证据池化（logit 加权）
    total_w = float(sum(s["weight"] for s in signals))
    if total_w <= 0:
        return {"state": "empty", "message": "没有可用证据（样本为空）"}
    pooled_logit = sum(s["weight"] * _logit(s["prob_a"]) for s in signals) / total_w
    p_game = _sigmoid(pooled_logit)
    se_logit = 1.0 / float(np.sqrt(total_w))
    p_lo = _sigmoid(pooled_logit - 1.96 * se_logit)
    p_hi = _sigmoid(pooled_logit + 1.96 * se_logit)
    if total_w < 30:
        warnings.append(f"等效样本偏低（Σn={total_w:.0f}），结果仅供参考")

    series_p = _series_prob(p_game, best_of)
    score_dist = _series_score_dist(p_game, best_of)
    return {
        "state": "ok",
        "version": SIM_VERSION,
        "mode": "赛前先验" if (len(lineup_a) < 3 or len(lineup_b) < 3) else "阵容假设",
        "team_a": team_a,
        "team_b": team_b,
        "best_of": best_of,
        "lineup_a": lineup_a,
        "lineup_b": lineup_b,
        "p_game": p_game,
        "p_game_ci": [p_lo, p_hi],
        "series_p": series_p,
        "series_ci": [_series_prob(p_lo, best_of), _series_prob(p_hi, best_of)],
        "score_dist": score_dist,
        "signals": signals,
        "total_weight": total_w,
        "warnings": warnings,
        "notes": [
            "独立同分布假设：未建模局间心理 / BP 学习效应（进阶见 P20）",
            "合成：logit 空间加权（权重=等效样本，封顶 120）；系列赛解析计算，可复现",
            "输出为「估算」，非官方预测",
        ],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def detect_events(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        cur = snapshots[i]
        minute = cur.get("minute", cur.get("minute_bin", 0))
        total_prev_kill = prev.get("camp1_kill", 0) + prev.get("camp2_kill", 0)
        total_cur_kill = cur.get("camp1_kill", 0) + cur.get("camp2_kill", 0)
        if total_prev_kill == 0 and total_cur_kill > 0:
            who = cur["camp1_team"] if cur.get("camp1_kill", 0) > prev.get("camp1_kill", 0) else cur["camp2_team"]
            events.append({"minute": minute, "type": "first_blood", "label": f"一血 · {who}", "team": who, "weight": 2})

        checks = [
            ("tower", "推塔", "camp1_tower", "camp2_tower", 3),
            ("tyrant", "暴君", "camp1_tyrant", "camp2_tyrant", 2),
            ("dark_tyrant", "黑暗暴君", "camp1_dark_tyrant", "camp2_dark_tyrant", 4),
            ("lord", "主宰", "camp1_lord", "camp2_lord", 5),
            ("storm", "风暴龙王", "camp1_storm", "camp2_storm", 8),
        ]
        for ev_type, name, c1_key, c2_key, weight in checks:
            c1_delta = cur.get(c1_key, 0) - prev.get(c1_key, 0)
            c2_delta = cur.get(c2_key, 0) - prev.get(c2_key, 0)
            if c1_delta > 0:
                events.append({"minute": minute, "type": ev_type, "label": f"{name} · {cur['camp1_team']}", "team": cur["camp1_team"], "weight": weight})
            if c2_delta > 0:
                events.append({"minute": minute, "type": ev_type, "label": f"{name} · {cur['camp2_team']}", "team": cur["camp2_team"], "weight": weight})
    return events


# Legacy big_dragon / lord overlaps prophet+shadow+storm; hide by default in P06 UI.
BIG_DRAGON_EVENT_TYPES = frozenset({"lord", "big_dragon"})
LANE_RESOURCE_POSITIONS = ("top", "jungle", "mid", "adc", "support")
LANE_RESOURCE_KPI_KEYS = (
    "lane_crush_count",
    "gold_diff_roll4",
    "gold_diff_roll10",
    "map_pressure_index",
    "objective_value_score",
    "obj_tower_convert",
    "resource_control_rate",
)


def _resolve_battle_snapshot_dir(battle_id: str) -> tuple[Path | None, str]:
    """Prefer raw_snapshots, then clean curated set."""
    battle_id = str(battle_id or "").strip()
    if not battle_id:
        return None, ""
    for root, label in ((RAW_DIR, "raw_snapshots"), (CLEAN_DIR, "clean")):
        battle_dir = root / battle_id
        if battle_dir.is_dir() and any(battle_dir.glob("*.json")):
            return battle_dir, f"{label}/{battle_id}"
    return None, ""


def _filter_lane_resource_events(
    events: list[dict[str, Any]],
    *,
    include_big_dragon: bool = False,
) -> list[dict[str, Any]]:
    """Drop legacy big_dragon/lord unless explicitly requested (avoids dual count)."""
    if include_big_dragon:
        return list(events)
    return [e for e in events if str(e.get("type") or "") not in BIG_DRAGON_EVENT_TYPES]


def _lane_timeline_sparse_gaps(
    minutes: list[float],
    *,
    gap_thresh: float = 1.5,
) -> list[dict[str, float]]:
    """Return minute holes larger than gap_thresh (no interpolation)."""
    gaps: list[dict[str, float]] = []
    for a, b in zip(minutes, minutes[1:]):
        try:
            lo = float(a)
            hi = float(b)
        except (TypeError, ValueError):
            continue
        if hi - lo > gap_thresh:
            gaps.append({"from_minute": lo, "to_minute": hi, "gap_min": hi - lo})
    return gaps


def build_lane_resource_timeline(
    battle_id: str,
    *,
    downsample_minute: bool = True,
    include_big_dragon: bool = False,
    sparse_gap_thresh: float = 1.5,
) -> dict[str, Any]:
    """Build five-lane gold-diff timeline + resource events + end-frame KPI.

    Lane gold diffs come from ``parse_snapshot`` player aggregates (official).
    KPI fields come from ``FeatureBuilder`` on the last kept frame (proxy, model-同源).
    Does **not** call ``predict_probability``.
    """
    battle_id = str(battle_id or "").strip()
    empty: dict[str, Any] = {
        "battle_id": battle_id,
        "source": "",
        "camp1_team": "",
        "camp2_team": "",
        "frames": [],
        "events": [],
        "events_raw_count": 0,
        "kpi": {},
        "sparse": False,
        "sparse_gaps": [],
        "has_level_diff": False,
        "has_hurt_diff": False,
        "empty": True,
        "message": "",
    }
    if not battle_id:
        empty["message"] = "缺少 battle_id"
        return empty

    battle_dir, source = _resolve_battle_snapshot_dir(battle_id)
    if battle_dir is None:
        empty["message"] = (
            f"未找到快照目录。请采集到 data/realtime/raw_snapshots/{battle_id} "
            "或确认 clean 数据集中有该局。"
        )
        return empty

    snaps = load_battle_jsons(battle_dir)
    if not snaps:
        empty["source"] = source
        empty["message"] = "快照目录存在但无可解析帧（status 非 1/2 或无有效 game_duration）。"
        return empty

    # Optional per-minute_bin downsample (keep first frame of each bin).
    kept: list[dict[str, Any]] = []
    if downsample_minute:
        seen_bins: set[int] = set()
        for snap in snaps:
            mb = max(int(snap.get("minute_bin") or snap.get("minute") or 1), 1)
            if mb in seen_bins:
                continue
            seen_bins.add(mb)
            kept.append(snap)
    else:
        kept = list(snaps)

    frames: list[dict[str, Any]] = []
    for snap in kept:
        minute = float(snap.get("minute") or snap.get("minute_bin") or 0)
        row: dict[str, Any] = {
            "minute": minute,
            "minute_bin": max(int(snap.get("minute_bin") or minute or 1), 1),
            "time_sec": int(snap.get("time_sec") or 0),
            "gold_diff": float(snap.get("camp1_gold", 0) or 0) - float(snap.get("camp2_gold", 0) or 0),
        }
        for pos in LANE_RESOURCE_POSITIONS:
            row[f"gold_diff_{pos}"] = float(snap.get(f"c1_gold_{pos}", 0) or 0) - float(
                snap.get(f"c2_gold_{pos}", 0) or 0
            )
            row[f"level_diff_{pos}"] = float(snap.get(f"c1_level_{pos}", 0) or 0) - float(
                snap.get(f"c2_level_{pos}", 0) or 0
            )
            row[f"hurt_diff_{pos}"] = float(snap.get(f"c1_hurt_{pos}", 0) or 0) - float(
                snap.get(f"c2_hurt_{pos}", 0) or 0
            )
        frames.append(row)

    minutes = [float(f["minute"]) for f in frames]
    sparse_gaps = _lane_timeline_sparse_gaps(minutes, gap_thresh=sparse_gap_thresh)

    # Events on full (non-downsampled) sequence so deltas are not missed.
    raw_events = detect_events(snaps)
    events = _filter_lane_resource_events(raw_events, include_big_dragon=include_big_dragon)

    kpi: dict[str, float] = {}
    if kept:
        history = list(kept[:-1])
        feats = FeatureBuilder().build(kept[-1], history)
        kpi = {k: float(feats.get(k, 0.0) or 0.0) for k in LANE_RESOURCE_KPI_KEYS}
        # Also expose per-lane diffs from last frame for ledger convenience.
        for pos in LANE_RESOURCE_POSITIONS:
            kpi[f"gold_diff_{pos}"] = float(feats.get(f"gold_diff_{pos}", 0.0) or 0.0)

    has_level = any(
        abs(float(f.get(f"level_diff_{pos}", 0) or 0)) > 0
        for f in frames
        for pos in LANE_RESOURCE_POSITIONS
    )
    has_hurt = any(
        abs(float(f.get(f"hurt_diff_{pos}", 0) or 0)) > 0
        for f in frames
        for pos in LANE_RESOURCE_POSITIONS
    )

    first = snaps[0]
    return {
        "battle_id": battle_id,
        "source": source,
        "camp1_team": str(first.get("camp1_team") or "Camp1"),
        "camp2_team": str(first.get("camp2_team") or "Camp2"),
        "frames": frames,
        "events": events,
        "events_raw_count": len(raw_events),
        "kpi": kpi,
        "sparse": bool(sparse_gaps),
        "sparse_gaps": sparse_gaps,
        "has_level_diff": has_level,
        "has_hurt_diff": has_hurt,
        "empty": False,
        "message": "",
        "snapshot_count": len(snaps),
        "frame_count": len(frames),
        "include_big_dragon": include_big_dragon,
    }


def build_lane_resource_ledger(
    timeline: dict[str, Any],
    *,
    first_n_minutes: float | None = None,
) -> list[dict[str, Any]]:
    """Resource ledger rows: event time + gold_diff snapshot at nearest frame."""
    frames = timeline.get("frames") or []
    events = timeline.get("events") or []
    if not events:
        return []
    rows: list[dict[str, Any]] = []
    for ev in events:
        try:
            m = float(ev.get("minute", 0) or 0)
        except (TypeError, ValueError):
            m = 0.0
        if first_n_minutes is not None and m > float(first_n_minutes):
            continue
        nearest: dict[str, Any] | None = None
        best_d = None
        for fr in frames:
            d = abs(float(fr.get("minute", 0) or 0) - m)
            if best_d is None or d < best_d:
                best_d = d
                nearest = fr
        nearest = nearest or {}
        row: dict[str, Any] = {
            "minute": m,
            "type": ev.get("type", ""),
            "label": ev.get("label", ""),
            "team": ev.get("team", ""),
            "weight": ev.get("weight", 0),
            "gold_diff": nearest.get("gold_diff", ""),
        }
        for pos in LANE_RESOURCE_POSITIONS:
            row[f"gold_diff_{pos}"] = nearest.get(f"gold_diff_{pos}", "")
        rows.append(row)
    rows.sort(key=lambda r: float(r.get("minute") or 0))
    return rows


def infer_stage_from_battle_id(battle_id: str, index: int = -1) -> str:
    """Resolve stage from schedule archive; never hard-code every battle as finals."""
    if not battle_id:
        return "本地数据"
    if SCHEDULE_ARCHIVE_PATH.exists():
        try:
            archive = pd.read_csv(SCHEDULE_ARCHIVE_PATH)
            for _, row in archive.iterrows():
                ids = [x for x in str(row.get("battle_ids") or "").split("|") if x]
                if battle_id not in ids:
                    continue
                stage = str(row.get("stage") or "").strip()
                round_name = str(row.get("round_name") or "").strip()
                if stage and stage not in ("未知赛段", "nan", "None"):
                    return stage
                if round_name and round_name not in ("未知轮次", "nan", "None"):
                    return round_name
                date = str(row.get("date") or "").strip()
                bo = row.get("bo_type", "")
                if date:
                    return f"{date} · BO{bo}" if bo != "" else date
        except (OSError, ValueError, KeyError):
            pass
    if index >= 0:
        return f"赛程局{index + 1}"
    return "常规赛"


def resolve_snapshot_root(*, from_raw: bool = False) -> Path:
    """Prefer curated clean set for train/backtest; fall back to raw ingest pool."""
    if from_raw:
        return RAW_DIR
    if CLEAN_DIR.exists() and any(CLEAN_DIR.iterdir()):
        return CLEAN_DIR
    return RAW_DIR


def load_battle_jsons(battle_dir: Path) -> list[dict[str, Any]]:
    rows = []
    seen_sec = set()
    for path in sorted(battle_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data = payload.get("data", {})
        if data.get("status", 0) not in (1, 2):
            continue
        sec = get_seconds(data.get("game_duration"))
        if sec in seen_sec:
            continue
        seen_sec.add(sec)
        rows.append(parse_snapshot(data, battle_dir.name))
    return sorted(rows, key=lambda x: x.get("time_sec", 0))


def fetch_official_winners(match_id: str = "2026052301") -> dict[str, tuple[int, str, str]]:
    result: dict[str, tuple[int, str, str]] = {}
    battle_rows = ScheduleCenter().fetch_battles(match_id)
    for battle in battle_rows:
        battle_id = str(battle.get("battle_id") or "")
        if not battle_id:
            continue
        data = api_get(BASE_URL_BATTLE, {"battle_id": battle_id}, timeout=10)
        bd = data.get("data", {}) if data else {}
        result[battle_id] = (
            int(bd.get("win_camp", 0) or 0),
            bd.get("camp1", {}).get("team_name", ""),
            bd.get("camp2", {}).get("team_name", ""),
        )
    return result


def load_replay_battles(match_id: str = "2026052301") -> list[dict[str, Any]]:
    official = fetch_official_winners(match_id)
    battles: list[dict[str, Any]] = []
    if not RAW_DIR.exists():
        return battles

    for idx, battle_dir in enumerate(sorted([p for p in RAW_DIR.iterdir() if p.is_dir()])):
        snapshots = load_battle_jsons(battle_dir)
        if len(snapshots) < 1:
            continue
        battle_id = battle_dir.name
        win_camp, api_c1, api_c2 = official.get(battle_id, (0, "", ""))
        if win_camp == 0:
            for snap in reversed(snapshots):
                if int(snap.get("status", 0) or 0) == 2 and int(snap.get("win_camp", 0) or 0) > 0:
                    win_camp = int(snap.get("win_camp", 0))
                    api_c1 = snap.get("camp1_team", "")
                    api_c2 = snap.get("camp2_team", "")
                    break
        api_winner = api_c1 if win_camp == 1 else api_c2 if win_camp == 2 else ""
        snap_c1 = snapshots[0].get("camp1_team", "")
        snap_c2 = snapshots[0].get("camp2_team", "")
        snap_win_camp = 1 if api_winner == snap_c1 else 2 if api_winner == snap_c2 else win_camp
        battles.append(
            {
                "battle_id": battle_id,
                "match_id": match_id,
                "game_no": idx + 1,
                "stage": infer_stage_from_battle_id(battle_id, idx),
                "camp1": snap_c1,
                "camp2": snap_c2,
                "winner": api_winner or (snap_c1 if snap_win_camp == 1 else snap_c2),
                "win_camp": snap_win_camp,
                "duration_min": snapshots[-1].get("minute", 0),
                "snapshots": snapshots,
                "events": detect_events(snapshots),
                "has_timeline": len({int(s.get("minute", 0)) for s in snapshots}) > 3,
                "snapshot_count": len(snapshots),
                "raw_path": str(battle_dir),
            }
        )
    return battles


def build_prediction_timeline(artifact: dict[str, Any], battle: dict[str, Any]) -> pd.DataFrame:
    rows = []
    history: deque[dict[str, Any]] = deque(maxlen=20)
    seen_minutes = set()
    for snap in battle.get("snapshots", []):
        minute_bin = max(int(snap.get("minute", 0)), 1)
        history.append(snap)
        if minute_bin in seen_minutes:
            continue
        seen_minutes.add(minute_bin)
        prob, feats, explain = predict_probability(artifact, snap, list(history))
        rows.append(
            {
                "battle_id": battle.get("battle_id"),
                "game_no": battle.get("game_no"),
                "minute": snap.get("minute", 0),
                "prob_camp1": prob,
                "prob_camp2": 1 - prob,
                "camp1": battle.get("camp1"),
                "camp2": battle.get("camp2"),
                "gold_diff": snap.get("camp1_gold", 0) - snap.get("camp2_gold", 0),
                "kill_diff": snap.get("camp1_kill", 0) - snap.get("camp2_kill", 0),
                "tower_diff": snap.get("camp1_tower", 0) - snap.get("camp2_tower", 0),
                "objective_value_score": feats.get("objective_value_score", 0),
                "tempo_swing_score": feats.get("tempo_swing_score", 0),
                "top_factor": explain[0]["factor"] if explain else "",
                "top_factor_leader": explain[0]["leader"] if explain else "",
                "correct": (prob >= 0.5 and battle.get("win_camp") == 1) or (prob < 0.5 and battle.get("win_camp") == 2),
            }
        )
    return pd.DataFrame(rows)


def build_team_summary(battles: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for battle in battles:
        final = battle["snapshots"][-1]
        for camp in (1, 2):
            team = battle.get(f"camp{camp}")
            opp = battle.get("camp2" if camp == 1 else "camp1")
            prefix = f"camp{camp}"
            other = "camp2" if camp == 1 else "camp1"
            rows.append(
                {
                    "team": team,
                    "opponent": opp,
                    "game_no": battle.get("game_no"),
                    "stage": battle.get("stage"),
                    "win": int(battle.get("winner") == team),
                    "duration_min": battle.get("duration_min", 0),
                    "gold": final.get(f"{prefix}_gold", 0),
                    "gold_diff": final.get(f"{prefix}_gold", 0) - final.get(f"{other}_gold", 0),
                    "kills": final.get(f"{prefix}_kill", 0),
                    "kill_diff": final.get(f"{prefix}_kill", 0) - final.get(f"{other}_kill", 0),
                    "towers": final.get(f"{prefix}_tower", 0),
                    "tower_diff": final.get(f"{prefix}_tower", 0) - final.get(f"{other}_tower", 0),
                    "tyrant": final.get(f"{prefix}_tyrant", 0),
                    "lord": final.get(f"{prefix}_lord", 0),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def data_health_report(battles: list[dict[str, Any]], schedule_matches: list[ScheduleMatch] | None = None) -> dict[str, Any]:
    snapshot_count = sum(b.get("snapshot_count", 0) for b in battles)
    latest_file = None
    if RAW_DIR.exists():
        files = list(RAW_DIR.glob("*/*.json"))
        latest_file = max(files, key=lambda p: p.stat().st_mtime) if files else None
    missing_timeline = [b["game_no"] for b in battles if not b.get("has_timeline")]
    teams = Counter()
    for b in battles:
        teams.update([b.get("camp1", ""), b.get("camp2", "")])
    return {
        "battle_count": len(battles),
        "snapshot_count": snapshot_count,
        "team_count": len([t for t in teams if t]),
        "schedule_count": len(schedule_matches or []),
        "latest_snapshot_file": str(latest_file) if latest_file else "无",
        "latest_snapshot_time": datetime.fromtimestamp(latest_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if latest_file else "无",
        "missing_timeline_games": missing_timeline,
        "raw_dir": str(RAW_DIR),
        "prediction_dir": str(PREDICTION_DIR),
    }


# ---------------------------------------------------------------------------
# 监控状态词表（单一事实源）
# 监控脚本（official_match_monitor）写、Dashboard 读；两边必须用同一套 canonical 状态，
# 否则“采集中”会被前端当成“状态异常”（历史 Bug：写 running、判 live）。
# ---------------------------------------------------------------------------
MONITOR_STATE_CANONICAL = {
    "live",             # 正在采集本局快照
    "waiting_start",    # 等待开赛 / 暂无可用赛程
    "waiting_battle",   # 已开赛，等待 BP / 首帧
    "battle_finished",  # 本局打完、等待下一局
    "training",         # 后台重训（采集不中断）
    "day_complete",     # 当日赛程完成
    "stopped",          # 被手动停止
    "error",            # 采集 / 接口 / 训练异常
    "not_started",      # 从未启动
}
# 监控脚本历史写法 → canonical
MONITOR_STATE_ALIASES = {
    "running": "live",
    "finished": "battle_finished",
    "waiting_schedule": "waiting_start",
    "waiting_next_match": "waiting_start",
    "starting": "waiting_battle",
    "ready": "waiting_battle",
    "api_error": "error",
    "train_error": "error",
    "status_error": "error",
}
# 这些状态表示“链路是活的、可以信任当前展示”，其余按陈旧/异常处理
MONITOR_STATE_HEALTHY = {"live", "waiting_start", "waiting_battle", "battle_finished", "training", "day_complete"}


def normalize_monitor_state(raw_state: Any) -> str:
    """把监控脚本写的 state 归一成 canonical 值（未知值原样返回）。"""
    s = str(raw_state or "not_started")
    s = MONITOR_STATE_ALIASES.get(s, s)
    return s if s in MONITOR_STATE_CANONICAL else s


def load_monitor_status() -> dict[str, Any]:
    """读取 monitor_status.json，并统一到 canonical 状态词表。

    返回体额外带 state_raw（原始写法）与 is_live（是否真的在采集），前端统一读这两个字段。
    """
    if not MONITOR_STATUS_FILE.exists():
        return {"state": "not_started", "state_raw": "not_started", "is_live": False,
                "message": "监控脚本尚未运行"}
    try:
        raw = json.loads(MONITOR_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"state": "error", "state_raw": "status_error", "is_live": False, "message": str(exc)}
    if not isinstance(raw, dict):
        return {"state": "error", "state_raw": "status_error", "is_live": False,
                "message": "monitor_status.json 结构异常"}
    state_raw = str(raw.get("state") or "not_started")
    state = normalize_monitor_state(state_raw)
    out = dict(raw)
    out["state_raw"] = state_raw
    out["state"] = state
    out["is_live"] = state == "live"
    out["healthy"] = state in MONITOR_STATE_HEALTHY
    return out


def load_kpl_knowledge(path: Path = KPL_KNOWLEDGE_PATH) -> dict[str, Any]:
    """Load configurable KPL/Honor of Kings domain knowledge for UI and features."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def historical_coverage_report(archive: pd.DataFrame | None = None) -> dict[str, Any]:
    """Summarize how much schedule and battle data has been cached locally."""
    center = ScheduleCenter()
    if archive is None:
        archive = center.load_schedule_archive()
    raw_battle_ids = {p.name for p in RAW_DIR.iterdir() if p.is_dir()} if RAW_DIR.exists() else set()
    archive_battle_ids: list[str] = []
    if archive is not None and not archive.empty and "battle_ids" in archive.columns:
        for value in archive["battle_ids"].fillna("").astype(str):
            archive_battle_ids.extend([x for x in value.split("|") if x])
    archive_set = set(archive_battle_ids)
    covered = archive_set & raw_battle_ids
    return {
        "archive_matches": 0 if archive is None or archive.empty else int(len(archive)),
        "archive_battles": int(len(archive_set)),
        "raw_battles": int(len(raw_battle_ids)),
        "covered_battles": int(len(covered)),
        "coverage_rate": float(len(covered) / len(archive_set)) if archive_set else 0.0,
        "missing_battles": sorted(archive_set - raw_battle_ids)[:50],
    }
