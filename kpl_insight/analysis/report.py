# -*- coding: utf-8 -*-
"""Human-readable Markdown rendering of the canonical report JSON."""
from __future__ import annotations


def _mv(v, unit: str = "") -> str:
    if v is None:
        return "—"
    if unit == "probability":
        return f"{float(v) * 100:.0f}%"
    if unit == "gold":
        return f"{float(v):+.0f}"
    return str(v)


def render_markdown(report: dict) -> str:
    s = report["series"]
    q = report["data_quality"]
    lines = [
        f"# {s['team1']} {s['score1']}:{s['score2']} {s['team2']} · 系列赛证据报告",
        "",
        f"> {s['date']} · {s['league_name']} · {s['stage']} · BO{s['bo']} · "
        f"数据状态：{q['status']}",
        "",
        "## 一句话结论",
        "",
        report["headline"],
        "",
        "## 数据完整性",
        "",
        f"- 总局数：{q['games']}",
        f"- 有分钟级快照：{q['games_with_minute_data']}/{q['games']}",
        f"- 有 BP：{q['games_with_bp']}/{q['games']}",
        f"- 生成时间：{report['generated_at']}",
    ]
    if q["warnings"]:
        lines += ["", "**警告（不补造）**："]
        lines += [f"- {w}" for w in q["warnings"]]
    lines += ["", "## 逐局事实", "",
              "| 局 | 胜方 | 胜方阵营 | 时长 | 5′金差 | 8′金差 | 10′金差 | 最终金差 |",
              "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for g in report["games"]:
        cp = g["checkpoints"]
        def gd(k):
            return _mv((cp.get(k) or {}).get("gold_diff_series_team1"), "gold")
        lines.append(
            f"| G{g['seq']} | {g['winner']} | {g['winner_side']} | {g['duration']:.0f}′ | "
            f"{gd('5')} | {gd('8')} | {gd('10')} | {_mv((g['final'] or {}).get('gold_diff_series_team1'), 'gold')} |"
        )
    lines += ["", "> 金差方向按系列赛 team1 视角；实际采样分钟见 `report.json` 的 checkpoints。", ""]

    lines += ["## 每局关键窗口", "",
              "> 窗口是候选变化段，不是因果判断；`估算` 来自胜率曲线，`代理` 来自金差。", ""]
    for g in report["games"]:
        w = g["windows"]
        lines.append(f"### G{g['seq']} · {g['team1']} vs {g['team2']}")
        if not g["coverage"]["has_minute_data"]:
            lines.append("- 本局无分钟级数据，不做窗口判断。")
            lines.append("")
            continue
        if w.get("model_last_valid_agrees_with_winner") is False:
            lines.append(f"- 模型最后有效帧（{w.get('last_valid_minute')}′）与官方胜方相反，"
                         "胜率窗口只作参考；不把被隔离的末帧当作终局判断。")
        if not w["candidates"]:
            lines.append("- 没有达到阈值的候选窗口。")
        for c in w["candidates"]:
            tag = "估算" if c["evidence_level"] == "estimate" else "代理"
            unit = c["unit"]
            lines.append(
                f"- {c['start_minute']:.1f}′–{c['end_minute']:.1f}′：{c['favored_team']} 占优；"
                f"变化 {_mv(c['from_value'], unit)} → {_mv(c['to_value'], unit)}（{tag}）；"
                f"同段事件：{' / '.join(c['events']) if c['events'] else '无结构性事件记录'}"
            )
        lines.append("")

    bp = report["bp"]
    lines += ["## BP 与阵容（只陈述选禁事实）", ""]
    for g in bp["per_game"]:
        lines.append(f"### G{g['seq']}")
        lines.append(f"- {g['team1']} picks：{'、'.join(g['picks1']) or '—'}")
        lines.append(f"- {g['team2']} picks：{'、'.join(g['picks2']) or '—'}")
        lines.append("")
    if bp["common_picks"]:
        lines.append("跨局重复 pick：" + "、".join(f"{x['hero']}（{x['games']} 局）" for x in bp["common_picks"]))
        lines.append("")

    comp = report["series_comparison"]
    lines += ["## 系列赛横向对比", "",
              f"- 胜方：{comp['winner']}",
              f"- 时长：{comp['durations']['min']:.0f}′–{comp['durations']['max']:.0f}′"
              f"（平均 {comp['durations']['avg']:.1f}′）",
              f"- 早期领先与最终胜方不一致：{('G' + '、G'.join(map(str, comp['comeback_games']))) if comp['comeback_games'] else '无'}",
              ""]
    lines += ["| 局 | 系列赛 team1 8′金差 | 早期领先 | 是否翻回 |", "|---:|---:|---|---|"]
    for g in report["games"]:
        cp = g["checkpoints"].get("8") or {}
        lines.append(f"| G{g['seq']} | {_mv(cp.get('gold_diff_series_team1'), 'gold')} | "
                     f"{g['early_leader'] or '—'} | {'是' if g['comeback'] else '否'} |")
    lines.append("")

    lines += ["## 事实 / 统计判断 / 假设", ""]
    for key, label in (("facts", "直接事实"), ("inferences", "统计判断"), ("hypotheses", "未证实假设")):
        lines.append(f"### {label}")
        for c in report["conclusion"][key]:
            lines.append(f"- {c['text']}")
        if not report["conclusion"][key]:
            lines.append("- 无")
        lines.append("")

    lines += ["## 口径与限制", ""]
    lines += [f"- {x}" for x in report["limits"]]
    lines += ["", "---", "", "由 `kpl_insight` 系列赛分析 V1 生成；结构化结果见同目录 JSON。"]
    return "\n".join(lines) + "\n"
