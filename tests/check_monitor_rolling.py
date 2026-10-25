"""监控选场的跨天回归测试（不联网，mock fetch_matches）。

背景（2026-10-18 事故）：
  monitor 进程以 `--date 2026-10-17` 启动后一直不重启，date 被钉死在启动日。
  那天比赛全结束后 `resolve_monitor_match` 恒为 None，进程持续 waiting_schedule，
  20:00 那场整场没被采集，页面还显示「待开赛」——进程活着，但做的是无效功。

修复：`resolve_monitor_match_rolling()` 把 date 从「锁定值」降级为「起始偏好」，
  按 偏好日 → 今天 → 未来 N 天 依次找第一个真有活可干的日期。

这个脚本把该行为固化下来。跑法：
    python tests/check_monitor_rolling.py
退出码 0 = 全通过，1 = 有失败项。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kpl_insight.core import ScheduleCenter, ScheduleMatch  # noqa: E402

let_fail: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    if not ok:
        let_fail.append(name)
    print(("PASS " if ok else "FAIL ") + name + (f"  → {extra}" if extra else ""))


def mk(match_id: str, when: datetime, status: int, t1: str = "A", t2: str = "B") -> ScheduleMatch:
    return ScheduleMatch(
        match_id=match_id,
        start_time=when,
        team1=t1,
        team2=t2,
        status=status,
        stage="测试赛段",
        round_name="测试轮次",
        bo_type="5",
        raw={"match_id": match_id, "status": status},
    )


def center_with(matches: list[ScheduleMatch]) -> ScheduleCenter:
    """造一个 fetch_matches 被 mock 掉的 ScheduleCenter（不联网）。"""
    sc = ScheduleCenter("0")
    sc.fetch_matches = lambda: matches  # type: ignore[method-assign]
    return sc


def main() -> int:
    now = datetime.now()
    today = now.date()
    yday = today - timedelta(days=1)
    tmrw = today + timedelta(days=1)

    # ---- 场景 1：昨天全结束，今天有一场正在进行 ----
    matches = [
        mk("Y1", datetime.combine(yday, datetime.min.time()) + timedelta(hours=17), 2, "昨队1", "昨队2"),
        mk("T1", now - timedelta(minutes=20), 1, "今队1", "今队2"),
        mk("M1", datetime.combine(tmrw, datetime.min.time()) + timedelta(hours=17), 0, "明队1", "明队2"),
    ]
    sc = center_with(matches)

    # 修复前的行为：锁定日期就找不到
    locked = sc.resolve_monitor_match(None, date=yday.strftime("%Y-%m-%d"))
    check("锁定过期日时旧逻辑返回 None（事故复现）", locked is None, str(locked))

    m, d = sc.resolve_monitor_match_rolling(yday.strftime("%Y-%m-%d"))
    check("过期日自动滚动到今天", d == today.strftime("%Y-%m-%d"), str(d))
    check("滚动后选中今天进行中的比赛", m is not None and m.match_id == "T1", m.match_id if m else "None")

    # ---- 场景 2：今天的也全结束了 → 应滚到明天 ----
    matches2 = [
        mk("Y1", datetime.combine(yday, datetime.min.time()) + timedelta(hours=17), 2, "昨队1", "昨队2"),
        mk("T1", now - timedelta(hours=3), 2, "今队1", "今队2"),
        mk("M1", datetime.combine(tmrw, datetime.min.time()) + timedelta(hours=17), 0, "明队1", "明队2"),
    ]
    sc2 = center_with(matches2)
    m2, d2 = sc2.resolve_monitor_match_rolling(yday.strftime("%Y-%m-%d"))
    check("今天全结束后滚到明天", d2 == tmrw.strftime("%Y-%m-%d"), str(d2))
    check("滚动后选中明天第一场", m2 is not None and m2.match_id == "M1", m2.match_id if m2 else "None")

    # ---- 场景 3：preferred 就是今天 → 不该乱跳 ----
    m3, d3 = sc.resolve_monitor_match_rolling(today.strftime("%Y-%m-%d"))
    check("preferred 为今天时仍选今天", d3 == today.strftime("%Y-%m-%d"), str(d3))
    check("preferred 为今天时选中 T1", m3 is not None and m3.match_id == "T1", m3.match_id if m3 else "None")

    # ---- 场景 4：完全没有可监控的比赛 → 明确返回 (None, None) ----
    sc4 = center_with([
        mk("Y1", datetime.combine(yday, datetime.min.time()) + timedelta(hours=17), 2, "昨队1", "昨队2"),
    ])
    m4, d4 = sc4.resolve_monitor_match_rolling(yday.strftime("%Y-%m-%d"))
    check("无比赛可监控时返回 (None, None)", m4 is None and d4 is None, f"{m4}, {d4}")

    # ---- 场景 5：未来 7 天窗口外不误选 ----
    far = today + timedelta(days=30)
    sc5 = center_with([
        mk("F1", datetime.combine(far, datetime.min.time()) + timedelta(hours=17), 0, "远队1", "远队2"),
    ])
    m5, d5 = sc5.resolve_monitor_match_rolling(yday.strftime("%Y-%m-%d"), max_days_ahead=7)
    check("超过 7 天窗口的比赛不会被选中", m5 is None, f"{m5}, {d5}")

    print()
    if let_fail:
        print(f"=== 失败 {len(let_fail)} 项 ===")
        print("失败项：" + " / ".join(let_fail))
        return 1
    print("=== 全部通过 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
