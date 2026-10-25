# -*- coding: utf-8 -*-
"""Series Intelligence V1 contract tests.

The synthetic fixture deliberately swaps battle sides between games: the same
series team is camp1 in G1 and camp2 in G2. A reader that trusts `win == 1`
instead of the team name will fail here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kpl_insight.analysis import analyze_series, load_series, render_markdown
from kpl_insight.analysis.loaders import DEFAULT_SITE_DIR, SeriesDataError


def _write_js(path: Path, name: str, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{name} = {json.dumps(obj, ensure_ascii=False)};\n", encoding="utf-8")


def _fixture(tmp_path: Path, *, corrupt: bool = False, score=(1, 1)) -> Path:
    assets = tmp_path / "assets"
    schedule = [{
        "matchId": "99990001", "leagueId": "9999", "leagueName": "Test League",
        "year": 2026, "stage": "Test", "date": "2026-01-01", "time": "18:00",
        "team1": "Alpha", "team2": "Bravo", "score1": score[0], "score2": score[1],
        "bo": 3, "done": True, "st": 2,
    }]
    _write_js(assets / "schedule_all.js", "KPL_SCHEDULE_ALL", schedule)

    index = {"99990001": {"lg": "9999", "b": [
        ["b1", 1, 10, 1, "Alpha", 3],
        ["b2", 2, 12, 2, "Bravo", 3],
    ]}}
    _write_js(assets / "games" / "index.js", "KPL_GAME_INDEX", index)

    details = {
        "b1": {"match": "99990001", "seq": 1, "win": 1, "dur": 10,
               "t1": "Alpha", "t2": "Bravo", "k1": 5, "k2": 2, "g1": 50000, "g2": 45000,
               "bp": [[1, 0, "HeroX"], [1, 1, "A1"], [2, 1, "B1"]], "players": []},
        # side switch: Bravo is detail t1 here, but the series team Bravo wins
        "b2": {"match": "99990001", "seq": 2, "win": 1, "dur": 12,
               "t1": "Bravo", "t2": "Alpha", "k1": 4, "k2": 3, "g1": 48000, "g2": 47000,
               "bp": [[1, 0, "HeroY"], [1, 1, "B2"], [2, 1, "A2"]], "players": []},
    }
    (assets / "games").mkdir(parents=True, exist_ok=True)
    (assets / "games" / "9999.json").write_text(json.dumps(details, ensure_ascii=False), encoding="utf-8")

    replay = {"matchId": "99990001", "date": "2026-01-01", "t1": "Alpha", "t2": "Bravo", "battles": [
        {"battleId": "b1", "seq": 1, "t1": "Alpha", "t2": "Bravo", "win": 1, "dur": 10,
         "frames": [
             {"m": 1, "p": 0.6, "gd": 100, "k": [0, 0], "t": [0, 0], "o": [[0, 0, 0, 0], [0, 0, 0, 0]]},
             {"m": 6, "p": 0.7, "gd": 900, "k": [2, 0], "t": [1, 0], "o": [[1, 0, 0, 0], [0, 0, 0, 0]]},
             {"m": 10, "p": 0.85, "gd": 1500, "k": [3, 1], "t": [2, 0], "o": [[1, 0, 0, 0], [0, 0, 0, 0]]},
         ],
         "events": [{"m": 6, "l": "推塔 · Alpha", "t": "tower"}]},
        {"battleId": "b2", "seq": 2, "t1": "Bravo", "t2": "Alpha", "win": 1, "dur": 12,
         "frames": [
             {"m": 1, "p": 0.55, "gd": -50, "k": [0, 0], "t": [0, 0], "o": [[0, 0, 0, 0], [0, 0, 0, 0]]},
             {"m": 7, "p": 0.7, "gd": 600, "k": [1, 0], "t": [0, 0], "o": [[1, 0, 0, 0], [0, 0, 0, 0]]},
             {"m": 12, "p": 0.8, "gd": 1000, "k": [4, 3], "t": [1, 0], "o": [[1, 0, 0, 0], [0, 0, 0, 0]]},
         ], "events": []},
    ]}
    (assets / "replay").mkdir(parents=True, exist_ok=True)
    (assets / "replay" / "99990001.json").write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    if corrupt:
        # cumulative tower regression: reader must quarantine, not silently keep it
        replay["battles"][1]["frames"][2]["t"] = [-1, 0]
        (assets / "replay" / "99990001.json").write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_side_switch_is_normalized_by_team(tmp_path):
    series = load_series("99990001", _fixture(tmp_path))
    assert (series.score1, series.score2) == (1, 1)
    assert series.games[0].winner == "Alpha"
    assert series.games[1].winner == "Bravo"
    assert series.games[1].side_of("Bravo") == 1
    report = analyze_series(series)
    seq = report["series_comparison"]["side_sequence"]
    assert seq[0]["team1_side"] == 1 and seq[1]["team1_side"] == 2


def test_cumulative_regression_is_quarantined_not_faked(tmp_path):
    series = load_series("99990001", _fixture(tmp_path, corrupt=True))
    assert any("推塔累计回退" in w for w in series.warnings)
    g2 = series.games[1]
    assert g2.quarantined_frames >= 1
    assert all(f.towers[0] >= 0 for f in g2.frames)
    report = analyze_series(series)
    assert report["data_quality"]["status"] == "degraded"


def test_score_mismatch_is_an_error(tmp_path):
    with pytest.raises(SeriesDataError, match="大场比分"):
        load_series("99990001", _fixture(tmp_path, score=(2, 0)))


def test_missing_replay_degrades_without_crashing(tmp_path):
    root = _fixture(tmp_path)
    (root / "assets" / "replay" / "99990001.json").unlink()
    series = load_series("99990001", root)
    assert any("缺少分钟级复盘包" in w for w in series.warnings)
    report = analyze_series(series)
    assert report["data_quality"]["status"] == "degraded"
    assert all(not g["coverage"]["has_minute_data"] for g in report["games"])
    assert all(not g["windows"]["candidates"] for g in report["games"])


def test_report_has_traceable_claims_and_markdown(tmp_path):
    report = analyze_series(load_series("99990001", _fixture(tmp_path)))
    assert report["schema_version"] == "1.0"
    assert report["conclusion"]["facts"]
    for claim in report["conclusion"]["facts"] + report["conclusion"]["inferences"]:
        assert claim.get("evidence")
    md = render_markdown(report)
    assert "系列赛证据报告" in md
    assert "未证实假设" in md


@pytest.mark.skipif(not (DEFAULT_SITE_DIR / "assets" / "replay" / "2026102201.json").exists(),
                    reason="real site assets are not available")
def test_real_hero_vs_lgd_orientation_and_degradation():
    series = load_series("2026102201")
    assert (series.team1, series.team2) == ("杭州LGD.NBW", "南通Hero久竞")
    assert (series.score1, series.score2) == (4, 0)
    assert [g.winner for g in series.games] == ["杭州LGD.NBW"] * 4
    # G1: Hero is detail t1, LGD is detail t2; G2/G3 reversed
    assert series.games[0].side_of("杭州LGD.NBW") == 2
    assert series.games[1].side_of("杭州LGD.NBW") == 1
    report = analyze_series(series)
    assert report["data_quality"]["status"] == "degraded"
    assert "G1 是唯一一局早期领先方" in report["headline"]
    g1 = report["games"][0]
    assert g1["early_leader"] == "南通Hero久竞"
    assert g1["comeback"] is True
