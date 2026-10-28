"""Manage only the fixed collector/exporter processes started by the local UI."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import threading


class RuntimeControl:
    def __init__(self, site: Path, root: Path | None = None):
        self.site = site.resolve()
        self.root = (root or Path(os.environ.get("KPL_DATA_ROOT") or Path.cwd())).resolve()
        self.source = Path(__file__).resolve().parents[1]
        self.private = (self.source / "scripts/official_match_monitor.py").is_file()
        if self.private and root is None:
            self.root = self.source
        self.runtime = self.root / "data/realtime/runtime"
        self.children: dict[str, subprocess.Popen] = {}
        self.handles: dict[str, object] = {}
        self.log_names: set[str] = set()
        self.mode = None
        self.league = None
        self.started_at = None
        self.error = ""
        self.lock = threading.RLock()
        self.ownership = None

    def model_files(self):
        candidates = [self.root / "output/models" / name for name in (
            "v9_official_platform.joblib", "v8_realtime_enhanced.joblib",
            "v7_realtime_stacking.joblib", "v6_realtime_calibrated.joblib", "v5_realtime_voting.joblib")]
        candidates.append(self.root / "data/realtime/model_backup/v9_official_platform.joblib")
        return [p for p in candidates if p.is_file()]

    def python(self):
        candidate = self.source / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
        return str(candidate if candidate.is_file() else Path(sys.executable))

    def commands(self, mode: str, league: str):
        monitor = ([self.python(), "-u", str(self.source / "scripts/official_match_monitor.py")]
                   if self.private else [self.python(), "-u", "-m", "kpl_insight.collection.monitor"])
        monitor += ["--league-id", league, "--interval", "3", "--no-auto-train"]
        if mode == "collect":
            monitor.append("--collect-only")
        exporter = ([self.python(), "-u", str(self.source / "scripts/build_live_data.py")]
                    if self.private else [self.python(), "-u", "-m", "kpl_insight.site.export_live"])
        return {"collector": monitor, **({"exporter": exporter + ["--watch", "30"]} if mode == "predict" else {})}

    def default_league(self):
        """Follow today's/next scheduled event, falling back to the latest archive."""
        rows = []
        try:
            with (self.root / "data/realtime/schedule_archive.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = [{"leagueId": row.get("league_id"), "date": row.get("date"), "st": row.get("status")} for row in csv.DictReader(handle)]
        except OSError:
            pass
        if not rows:
            try:
                text = (self.site / "assets/schedule_all.js").read_text(encoding="utf-8")
                rows = json.loads(text.split("=", 1)[1].strip().rstrip(";"))
            except (OSError, ValueError, IndexError):
                rows = []
        rows = [row for row in rows if isinstance(row, dict) and str(row.get("leagueId", "")).isascii()
                and str(row.get("leagueId", "")).isdigit() and len(str(row["leagueId"])) <= 12
                and int(row["leagueId"]) > 0 and isinstance(row.get("date"), str)]
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        pending = [row for row in rows if row["date"] >= today and str(row.get("st")) != "2"]
        if pending:
            chosen = min(pending, key=lambda row: (row["date"], str(row.get("st")) != "1"))
        elif rows:
            past = [row for row in rows if row["date"] <= today]
            chosen = max(past, key=lambda row: row["date"]) if past else min(rows, key=lambda row: row["date"])
        else:
            raise ValueError("尚未找到可用赛程，请更新项目数据后重试。")
        return str(chosen["leagueId"])

    def _claim(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        handle = (self.runtime / "web-control.lock").open("a+b")
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise ValueError("另一个本地控制面板已启动采集，请先在原面板停止。") from None
        self.ownership = handle

    def _release(self):
        if self.ownership:
            self.ownership.close()
            self.ownership = None

    def _tail(self, name):
        try:
            with (self.runtime / f"web-{name}.log").open("rb") as handle:
                handle.seek(0, 2)
                handle.seek(max(0, handle.tell() - 16000))
                return handle.read().decode("utf-8", errors="replace")[-12000:]
        except OSError:
            return ""

    def external_collector(self):
        """Recognize the development collector's OS lock without taking ownership."""
        path = self.runtime / "collector.lock"
        if not self.private or "collector" in self.children or not path.is_file():
            return False
        try:
            with path.open("r+b") as handle:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except OSError:
            return True

    def status(self):
        with self.lock:
            states = {name: {"running": p.poll() is None, "pid": p.pid, "exit_code": p.poll()}
                      for name, p in self.children.items()}
            if states and any(not state["running"] for state in states.values()):
                # A partial pipeline must never be presented as healthy.
                if any(state["exit_code"] not in (None, 0) for state in states.values()):
                    self.error = "采集或导出程序异常退出，请查看日志。"
                elif any(state["running"] for state in states.values()):
                    self.error = "部分程序已退出，实时链路不完整。请先停止再重新启动。"
            if states and not any(state["running"] for state in states.values()):
                self._release()
            live = self.site / "assets/live.js"
            updated = datetime.fromtimestamp(live.stat().st_mtime, timezone.utc).isoformat() if live.exists() else None
            report = {}
            try:
                sources = [self.root / "data/realtime/monitor_status.json"]
                if self.private:
                    sources.append(self.runtime / "collector_status.json")
                sources = [path for path in sources if path.is_file()]
                if sources:
                    report = json.loads(max(sources, key=lambda path: path.stat().st_mtime).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                pass
            record_age = None
            record_current = False
            try:
                updated_at = datetime.fromisoformat(report["updated_at"]).timestamp()
                record_age = max(0, datetime.now().timestamp() - updated_at)
                record_current = bool(self.started_at) and updated_at >= datetime.fromisoformat(self.started_at).timestamp() - 2
            except (KeyError, ValueError, TypeError):
                pass
            return {"mode": self.mode, "league": self.league, "started_at": self.started_at,
                    "model_found": bool(self.model_files()), "processes": states,
                    "external_collector": self.external_collector(),
                    "running": bool(states) and all(s["running"] for s in states.values()),
                    "error": self.error, "live_updated_at": updated,
                    "collector_record": {k: report.get(k) for k in ("state", "message", "updated_at", "match_id", "battle_id")},
                    "record_age_seconds": record_age, "record_from_current_run": record_current,
                    "logs": {name: self._tail(name) for name in sorted(self.log_names)}}

    def start(self, mode="auto", league=None):
        with self.lock:
            if mode == "auto":
                league = self.default_league()
                mode = "predict" if self.model_files() else "collect"
            if mode not in ("collect", "predict") or not isinstance(league, str) or not league.isascii() or not league.isdigit() or not 1 <= len(league) <= 12 or int(league) <= 0:
                raise ValueError("请选择有效模式并填写数字赛事 ID。")
            if any(p.poll() is None for p in self.children.values()):
                raise ValueError("已有本面板启动的程序正在运行，请先停止。")
            if self.external_collector():
                raise ValueError("检测到其他终端运行的采集程序，请先在原终端停止后再使用本面板。")
            if mode == "predict" and not self.model_files():
                raise ValueError("未找到模型。请先选择“仅采集”，按 README 训练并验证模型后再启动实时预测。")
            # Check dependencies with the actual worker interpreter, without importing models.
            check = subprocess.run([self.python(), "-c", "import importlib.util,json; print(json.dumps([n for n in ['requests','pandas','numpy','joblib','sklearn','scipy'] if importlib.util.find_spec(n) is None]))"],
                                   capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if check.returncode or json.loads(check.stdout or "[]"):
                raise ValueError("采集环境缺少依赖，请先按 README 在项目环境中安装 requirements.txt。")
            self.stop()
            self._claim()
            self.mode, self.league = mode, league
            self.started_at = datetime.now(timezone.utc).isoformat()
            self.error = ""
            env = dict(os.environ, KPL_SITE_DIR=str(self.site), KPL_DATA_ROOT=str(self.root), PYTHONIOENCODING="utf-8")
            env["PYTHONPATH"] = str(self.source) + os.pathsep + env.get("PYTHONPATH", "")
            try:
                for name, command in self.commands(mode, league).items():
                    handle = (self.runtime / f"web-{name}.log").open("ab")
                    self.handles[name] = handle
                    self.log_names.add(name)
                    handle.write(f"\n--- {self.started_at} {mode} league={league} ---\n".encode())
                    handle.flush()
                    self.children[name] = subprocess.Popen(command, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                        stdout=handle, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                self.stop()
                raise
            return self.status()

    def stop(self):
        with self.lock:
            for process in self.children.values():
                if process.poll() is None:
                    process.terminate()
            for process in self.children.values():
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for handle in self.handles.values():
                handle.close()
            self.children.clear()
            self.handles.clear()
            self._release()
            self.error = ""
            return self.status()
