"""
KPL 数据中心 · 全新前端

运行：streamlit run apps/dashboard.py
"""
from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kpl_insight.core import (
    aggregate_bp_meta,
    build_hero_matchups,
    build_hero_pool,
    build_lane_resource_timeline,
    build_phase_attribution,
    build_postmatch_brief,
    build_proxy_standings,
    build_season_honors,
    build_winprob_benchmark,
    classify_battle_swing,
    detect_events,
    detect_turning_points,
    filter_teams_window,
    generate_battle_report,
    hero_meta_rows_for_battle,
    historical_coverage_report,
    load_battle_bp,
    load_battle_jsons,
    load_battle_players,
    load_model,
    load_monitor_status,
    resolve_snapshot_root,
    simulate_series,
    summarize_winprob_benchmark_phases,
    team_style_radar,
)

from kpl_insight.paths import PROJECT_ROOT
ANALYSIS_DIR = PROJECT_ROOT / "data" / "analysis"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REALTIME_DIR = PROJECT_ROOT / "data" / "realtime"
PREDICTION_DIR = REALTIME_DIR / "predictions"
RAW_DIR = REALTIME_DIR / "raw_snapshots"

# ---------------- 设计 Token（00-设计系统与UI规范） ----------------
BLUE = "#005691"
BLUE_D = "#003E66"
RED = "#C0392B"
ORANGE = "#FF8C00"
ORANGE_D = "#E67E00"
TEAL = "#20B2AA"
PURPLE = "#8A2BE2"
YELLOW = "#F5B301"
INK = "#1F2937"
INK_2 = "#5D6D7E"
MUTED = "#8A94A6"
BG = "#F4F6F8"
CARD = "#FFFFFF"
LINE = "#E3E8EE"
LINE_2 = "#B8C2CC"
MONO = '"Roboto Mono","JetBrains Mono","Sarasa Mono SC",Consolas,monospace'
SANS = '"Inter","Segoe UI","PingFang SC","Microsoft YaHei",sans-serif'

SRC_STYLES = {
    "官方": (BLUE, "#EEF4FA"),
    "代理": (TEAL, "#EAF7F6"),
    "估算": (PURPLE, "#F4EFFC"),
    "舆情": (ORANGE, "#FFF4E6"),
    "营地": (MUTED, "#F1F3F5"),
    "人工": (INK, "#F1F3F5"),
    "自算荣誉": (INK, "#F1F3F5"),
    "描述性": (TEAL, "#EAF7F6"),
    "叙事因子": (MUTED, "#F1F3F5"),
}

TEAM_COLORS = {
    "成都AG超玩会": RED, "重庆狼队": ORANGE, "广州TTG": PURPLE, "苏州KSG": TEAL,
    "KSG": TEAL, "北京WB": BLUE, "武汉eStarPro": RED, "佛山DRG": BLUE,
    "深圳DYG": TEAL, "济南RW侠": ORANGE, "上海EDG.M": RED, "杭州LGD.NBW": PURPLE,
    "南通Hero久竞": TEAL, "北京JDG": BLUE, "西安WE": ORANGE, "长沙TES.A": RED,
    "SYG": PURPLE, "WST": BLUE,
}
PALETTE = [BLUE, RED, ORANGE, TEAL, PURPLE, INK, "#0E9F8F", "#D97706"]

MODULES = [
    ("schedule", "赛事中心", "◆"),
    ("live", "实时中控", "▲"),
    ("replay", "单局复盘", "■"),
    ("teams", "战队画像", "●"),
    ("players", "选手排行", "◀"),
    ("heroes", "英雄 Meta", "◇"),
    ("sim", "大场模拟", "▣"),
    ("ops", "数据健康", "▼"),
]
MODULE_OPTS = [f"{glyph} {name}" for _code, name, glyph in MODULES]
MODULE_BY_LABEL = {f"{glyph} {name}": code for code, name, glyph in MODULES}

EVENT_CN = {
    "first_blood": "一血", "tower": "推塔", "tyrant": "暴君",
    "dark_tyrant": "黑暗暴君", "lord": "主宰", "storm": "风暴龙王", "big_dragon": "大龙",
}
LANES = ["对抗路", "打野", "中路", "发育路", "游走"]


def team_color(team: str) -> str:
    if team in TEAM_COLORS:
        return TEAM_COLORS[team]
    return PALETTE[sum(ord(c) for c in str(team)) % len(PALETTE)]


def _esc(v: object) -> str:
    return html.escape(str(v if v is not None else "—"))


def fmt_int(v: object) -> str:
    try:
        f = float(v)
        return "—" if pd.isna(f) else f"{int(f):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_num(v: object, nd: int = 0) -> str:
    try:
        f = float(v)
        return "—" if pd.isna(f) else f"{f:,.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def fmt_signed(v: object, nd: int = 0) -> str:
    try:
        f = float(v)
        return "—" if pd.isna(f) else f"{f:+,.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(v: object, nd: int = 1) -> str:
    try:
        f = float(v)
        return "—" if pd.isna(f) else f"{f * 100:.{nd}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_min(v: object) -> str:
    try:
        f = float(v)
        return "—" if pd.isna(f) else f"{f:.0f}′"
    except (TypeError, ValueError):
        return "—"


def safe_f(v: object, nd: int = 4) -> str:
    try:
        f = float(v)
        return "—" if pd.isna(f) else f"{f:.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def bench_with_prob(bench: pd.DataFrame) -> pd.DataFrame:
    if bench is None or bench.empty:
        return bench
    out = bench.copy()
    out["camp1_win_prob"] = out["p_v11"]
    return out


def selected_points(key: str) -> list[dict]:
    try:
        return list(st.session_state[key]["selection"]["points"])
    except (KeyError, TypeError):
        return []


# ---------------- 样式表 ----------------
LIGHT_VARS = """
  --blue:#005691; --blue-d:#003E66; --red:#C0392B; --orange:#FF8C00; --orange-d:#E67E00;
  --teal:#20B2AA; --purple:#8A2BE2; --yellow:#F5B301;
  --ink:#1F2937; --ink2:#5D6D7E; --muted:#8A94A6;
  --bg:#F4F6F8; --card:#FFFFFF; --line:#E3E8EE; --line2:#B8C2CC;
  --row-hover:#F2F6FA; --head-bg:#EAF0F6; --shadow:0 1px 2px rgba(16,24,40,.04),0 6px 18px rgba(16,24,40,.05);
  --shadow-hover:0 2px 4px rgba(16,24,40,.06),0 14px 32px rgba(16,24,40,.10);
"""
DARK_VARS = """
  --blue:#3B9EFF; --blue-d:#2C7FD8; --red:#FF6B5E; --orange:#FF9F2E; --orange-d:#E67E00;
  --teal:#3ECFC7; --purple:#A974FF; --yellow:#FFC94D;
  --ink:#E8EDF3; --ink2:#AAB4C0; --muted:#7C8694;
  --bg:#0E1218; --card:#151B23; --line:#232B35; --line2:#36404C;
  --row-hover:#1A2230; --head-bg:#1B242F; --shadow:0 1px 2px rgba(0,0,0,.4),0 6px 18px rgba(0,0,0,.25);
  --shadow-hover:0 2px 4px rgba(0,0,0,.5),0 14px 32px rgba(0,0,0,.35);
"""

def build_css(dark: bool) -> str:
    return f"""<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<style>
:root {{
{DARK_VARS if dark else LIGHT_VARS}
}}
{CSS_BODY}
{DARK_OVERRIDES if dark else ""}
</style>"""


DARK_OVERRIDES = """
.mu-blue { background:linear-gradient(180deg,#12242F,#0E1E28) !important; }
.mu-red { background:linear-gradient(180deg,#301615,#29100E) !important; }
.topbar { background:#0B2A44 !important; box-shadow:0 8px 24px rgba(0,0,0,.4) !important; }
.bp-pick { color:#8FC0EE; background:rgba(59,158,255,.14); border:1px solid rgba(59,158,255,.35); }
.bp-ban { color:var(--muted); background:var(--bg); border:1px solid var(--line); }
.b-live { color:var(--teal); border-color:var(--teal); background:rgba(62,207,199,.12); }
.b-clean { color:var(--blue); border-color:var(--blue); background:rgba(59,158,255,.12); }
.b-quar { color:var(--purple); border-color:var(--purple); background:rgba(169,116,255,.14); }
.b-wait { color:var(--orange); border-color:var(--orange); background:rgba(255,159,46,.12); }
.b-err { color:var(--red); border-color:var(--red); background:rgba(255,107,94,.12); }
.b-done { color:var(--muted); border-color:var(--line2); background:var(--bg); }
.lb-rank { background:#2A3442; }
.mcard-date { background:#0B2A44; }
.timg { box-shadow:inset 0 0 0 1px var(--line2); }
"""


CSS_BODY = """
@import url('https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;500;700&display=swap');
html, body, .stApp { background: var(--bg) !important; color: var(--ink); }
[data-testid="stHeader"] { background: transparent !important; }
#MainMenu, footer { visibility: hidden; }
.block-container { max-width: 1400px; padding: 0 1.25rem 4rem; }
h1, h2, h3, h4 { font-family: var(--mono) !important; color: var(--ink) !important;
  font-weight: 700; letter-spacing: -0.02em; }
p, li, label, .stCaption { color: var(--ink2); font-size: 0.9rem; font-family: var(--sans); }
a { color: var(--blue); }

/* ---- 顶栏 ---- */
.topbar { display:flex; align-items:center; justify-content:space-between; gap:16px;
  min-height:64px; background:var(--blue); color:#fff; border-radius:12px;
  padding:10px 20px; margin:1rem 0 14px; position:relative; overflow:hidden;
  box-shadow:0 8px 24px rgba(0,86,145,.22); }
.topbar::after { content:""; position:absolute; right:-46px; top:-34px; width:190px; height:130px;
  background:var(--orange); transform:rotate(26deg); opacity:.96; }
.topbar::before { content:""; position:absolute; right:96px; top:-60px; width:130px; height:180px;
  background:rgba(255,255,255,.08); transform:rotate(26deg); }
.brand { display:flex; align-items:center; gap:14px; position:relative; z-index:1; }
.brand-mark { width:26px; height:26px; background:var(--orange); transform:rotate(45deg);
  box-shadow:0 0 0 4px rgba(255,255,255,.22); flex:0 0 auto; }
.brand-name { font-size:18px; font-weight:700; letter-spacing:.6px; color:#fff;
  font-family:var(--mono); }
.brand-sub { font-size:10px; color:rgba(255,255,255,.72); letter-spacing:2.6px;
  text-transform:uppercase; font-family:var(--mono); }
.topmeta { display:flex; align-items:center; gap:8px; flex-wrap:wrap; position:relative; z-index:1; }
.chip { font-size:11px; color:rgba(255,255,255,.92); background:rgba(255,255,255,.12);
  border:1px solid rgba(255,255,255,.32); border-radius:6px; padding:5px 11px;
  white-space:nowrap; font-family:var(--mono); letter-spacing:.3px; }
.chip b { color:#fff; font-weight:700; }
.chip .dot-live { display:inline-block; width:8px; height:8px; background:var(--yellow);
  margin-right:6px; animation:pulse 1.6s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.25} }

/* ---- 侧栏（模块轨） ---- */
[data-testid="stSidebar"] { background:var(--card); border-right:1px solid var(--line); }
[data-testid="stSidebar"] .block-container { padding: 0.9rem 0.8rem; }
.side-brand { display:flex; align-items:center; gap:10px; font-family:var(--mono);
  font-size:14px; font-weight:700; color:var(--ink); padding:2px 6px 14px; }
.side-brand .brand-mark { width:15px; height:15px; background:var(--orange); transform:rotate(45deg); }
.nav-group { font-size:9.5px; color:var(--muted); letter-spacing:2px; margin:14px 8px 6px;
  text-transform:uppercase; font-family:var(--mono); font-weight:500; }
.nav-group::before { content:"■"; color:var(--orange); font-size:7px; margin-right:7px;
  vertical-align:1px; }
.side-foot { margin-top:14px; padding:12px 8px 2px; border-top:1px solid var(--line);
  font-size:10.5px; color:var(--muted); line-height:2; font-family:var(--mono); }
.side-foot b { color:var(--ink); font-weight:700; }

[data-testid="stSidebar"] [data-testid="stRadio"] { width:100%; }
[data-testid="stSidebar"] [data-testid="stRadio"] > div[role="radiogroup"] {
  gap:3px; width:100%; }
[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"] {
  display:flex; align-items:center; gap:10px; padding:9px 11px; border-radius:8px;
  border:1px solid transparent; color:var(--ink2); font-size:13px;
  font-family:var(--mono); cursor:pointer; transition:all .15s ease-out;
  width:100%; box-sizing:border-box; }
[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:hover {
  background:var(--row-hover); color:var(--ink); }
[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
  background:var(--blue); color:#fff; font-weight:700;
  box-shadow:0 4px 12px rgba(0,86,145,.25); }
[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child {
  width:12px; height:12px; border:2px solid var(--line2); background:#fff; border-radius:2px; }
[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) > div:first-child {
  border-color:var(--yellow); background:var(--yellow); box-shadow:inset 0 0 0 2px #fff; }
[data-testid="stSidebar"] [data-testid="stRadio"] > label[data-testid="stWidgetLabel"] { display:none; }

/* 输入控件 */
[data-testid="stSelectbox"] > div > div, [data-testid="stMultiselect"] > div > div,
[data-testid="stMultiSelect"] > div > div {
  background:var(--card) !important; border-color:var(--line2) !important; color:var(--ink) !important;
  border-radius:8px; box-shadow:var(--shadow); }
[data-testid="stSelectbox"] span, [data-testid="stMultiselect"] span, [data-testid="stMultiSelect"] span {
  color:var(--ink) !important; font-family:var(--mono); font-size:12.5px; }
div[data-baseweb="select"] > div { background:var(--card) !important; }
[data-testid="stSelectbox"] [role="listbox"], [data-testid="stMultiselect"] [role="listbox"],
[data-testid="stMultiSelect"] [role="listbox"] { background:var(--card) !important; }
[data-testid="stToggle"] label { font-family:var(--mono); }
[data-testid="stToggle"] label > div:first-child { background:var(--line2); }
[data-testid="stToggle"] label > div:first-child[data-checked="true"] { background:var(--blue); }

/* 按钮 */
.stButton > button { background:var(--card); border:1.5px solid var(--line2); color:var(--blue);
  border-radius:8px; font-size:12.5px; font-family:var(--mono); font-weight:500;
  transition:all .18s ease-out; }
.stButton > button:hover { border-color:var(--orange); color:var(--orange-d);
  box-shadow:0 4px 14px rgba(16,24,40,.10); transform:translateY(-1px); }
.stButton > button[kind="primary"], .stButton > button[kind="primaryFormSubmit"] {
  background:var(--orange); color:#fff; font-weight:700; border-color:var(--orange);
  box-shadow:0 4px 14px rgba(255,140,0,.28); }
.stButton > button[kind="primary"]:hover { background:var(--orange-d); }

/* Tabs */
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap:4px; border-bottom:2px solid var(--line);
  padding-bottom:0; }
[data-testid="stTabs"] [data-baseweb="tab"] { color:var(--ink2); font-size:13px; padding:9px 18px;
  font-family:var(--mono); border-radius:8px 8px 0 0; }
[data-testid="stTabs"] [data-baseweb="tab"]:hover { color:var(--blue); background:var(--row-hover); }
[data-testid="stTabs"] [aria-selected="true"] { color:var(--blue); font-weight:700; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { background-color:var(--orange); height:3px; }

/* 数据表 */
[data-testid="stDataFrame"] { background:transparent; font-family:var(--mono); font-size:12px; }
[data-testid="stDataFrame"] [data-testid="stDataFrameTable"] { color:var(--ink); }

/* ---- 页头 ---- */
.page-head { display:flex; align-items:flex-end; justify-content:space-between;
  gap:12px; margin:10px 0 20px; flex-wrap:wrap; }
.page-kicker { font-size:10px; color:var(--orange); letter-spacing:2.4px; margin-bottom:8px;
  text-transform:uppercase; font-family:var(--mono); font-weight:500; display:flex; align-items:center; gap:8px; }
.page-kicker::before { content:""; width:18px; height:2px; background:var(--orange); }
.page-title { font-size:26px; font-weight:700; color:var(--ink); letter-spacing:-.02em;
  font-family:var(--mono); display:flex; align-items:center; }
.page-title::before { content:""; width:14px; height:14px; background:var(--orange);
  transform:rotate(45deg); margin-right:14px; flex:0 0 auto;
  box-shadow:0 0 0 5px rgba(255,140,0,.14); }
.page-title .inline-tag { margin-left:10px; vertical-align:2px; }
.page-sub { font-size:12.5px; color:var(--muted); margin-top:6px; margin-left:33px;
  font-family:var(--mono); }
.page-right { display:flex; gap:8px; align-items:center; }

/* ---- 上下文条 ---- */
.ctx-bar { display:flex; align-items:center; gap:8px; flex-wrap:wrap; background:var(--card);
  border:1px solid var(--line); border-left:4px solid var(--blue); border-radius:8px;
  padding:9px 14px; margin-bottom:16px; box-shadow:var(--shadow); }
.ctx-label { font-size:10px; color:var(--muted); letter-spacing:1.4px; text-transform:uppercase;
  font-family:var(--mono); margin-right:4px; }
.ctx-chip { font-family:var(--mono); font-size:12px; font-weight:600; color:var(--ink);
  background:var(--bg); border:1px solid var(--line); border-radius:6px; padding:4px 10px; }
.ctx-chip b { color:var(--blue); }
.ctx-clear { margin-left:auto; }

/* ---- 面板 ---- */
.panel { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; margin-bottom:14px; box-shadow:var(--shadow); }
.panel-sunken { background:var(--bg); box-shadow:none; }
.panel-title { font-size:11.5px; font-weight:700; color:var(--ink); margin-bottom:12px;
  display:flex; align-items:center; gap:9px; font-family:var(--mono);
  text-transform:uppercase; letter-spacing:.8px; }
.panel-title::before { content:""; width:8px; height:18px; background:var(--blue); flex:0 0 auto;
  border-radius:2px; }

/* ---- 来源标签 ---- */
.stg { display:inline-block; font-size:9.5px; font-weight:500; letter-spacing:.9px;
  border:1px solid; border-radius:4px; padding:1.5px 8px; white-space:nowrap;
  font-family:var(--mono); }

/* ---- 统计块 ---- */
.stat-row { display:grid; gap:12px; margin-bottom:16px; }
.kpi { background:var(--card); border:1px solid var(--line); border-top:4px solid var(--blue);
  border-radius:10px; padding:16px 18px 14px; box-shadow:var(--shadow); transition:all .18s ease-out;
  position:relative; overflow:hidden; }
.kpi:hover { box-shadow:var(--shadow-hover); transform:translateY(-1px); }
.kpi::after { content:""; position:absolute; right:-2px; top:-2px; width:0; height:0;
  border-style:solid; border-width:0 30px 30px 0;
  border-color:transparent rgba(255,140,0,.10) transparent transparent; }
.kpi.bar-orange { border-top-color:var(--orange); }
.kpi.bar-purple { border-top-color:var(--purple); }
.kpi.bar-teal { border-top-color:var(--teal); }
.kpi.bar-red { border-top-color:var(--red); }
.kpi-top { display:flex; align-items:center; gap:8px; margin-bottom:9px; }
.kpi-label { font-size:10px; color:var(--muted); letter-spacing:1.2px;
  text-transform:uppercase; font-family:var(--mono); font-weight:500; }
.kpi-value { font-family:var(--mono); font-size:33px; font-weight:700; color:var(--ink);
  line-height:1.05; letter-spacing:-.03em; }
.kpi-value.t-up { color:var(--teal); } .kpi-value.t-down { color:var(--red); }
.kpi-value.t-warn { color:var(--orange); } .kpi-value.t-acc { color:var(--blue); }
.kpi-delta { font-family:var(--mono); font-size:11.5px; margin-top:4px; color:var(--ink2); }
.kpi-note { font-size:11px; color:var(--muted); margin-top:4px; line-height:1.5;
  font-family:var(--mono); }

/* ---- 对阵 ---- */
.matchup { display:flex; align-items:stretch; border:1px solid var(--line); border-radius:12px;
  overflow:hidden; background:var(--card); box-shadow:var(--shadow); }
.mu-team { flex:1; padding:16px 18px; display:flex; flex-direction:column; gap:5px; }
.mu-blue { background:linear-gradient(180deg,#F2F7FB,#EAF2F9); border-right:1px solid var(--line); }
.mu-red { background:linear-gradient(180deg,#FBF3F2,#F8ECEA); text-align:right; }
.mu-head { display:flex; align-items:center; gap:8px; }
.mu-blue .mu-head { justify-content:flex-start; }
.mu-red .mu-head { justify-content:flex-end; }
.mu-name { font-size:16px; font-weight:700; color:var(--ink); font-family:var(--mono);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.mu-tag { font-size:9px; font-weight:700; color:#fff; background:var(--orange);
  border-radius:4px; padding:2px 7px; letter-spacing:1px; font-family:var(--mono); }
.mu-score { font-family:var(--mono); font-size:34px; font-weight:700; line-height:1;
  color:var(--ink); }
.mu-pct { font-family:var(--mono); font-size:12.5px; font-weight:700; letter-spacing:.3px; }
.mu-center { width:126px; background:var(--ink); color:#fff; display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:9px; padding:12px 8px; position:relative; }
.mu-center::before { content:""; width:10px; height:10px; background:var(--orange);
  transform:rotate(45deg); position:absolute; top:10px; }
.mu-vs { font-family:var(--mono); font-size:16px; font-weight:700; letter-spacing:3px;
  color:var(--yellow); }
.mu-split { width:100%; height:7px; background:rgba(255,255,255,.18); display:flex; border-radius:4px;
  overflow:hidden; }
.mu-fill { height:100%; }
.mu-sub { font-size:10px; color:rgba(255,255,255,.78); font-family:var(--mono);
  text-align:center; line-height:1.5; }

/* ---- 徽章 ---- */
.bdg { display:inline-block; font-size:9.5px; font-weight:700; letter-spacing:.9px;
  border-radius:4px; padding:2.5px 9px; border:1.5px solid; white-space:nowrap;
  font-family:var(--mono); }
.b-live { color:var(--teal); border-color:var(--teal); background:#EAF7F6; }
.b-clean { color:var(--blue); border-color:var(--blue); background:#EEF4FA; }
.b-quar { color:var(--purple); border-color:var(--purple); background:#F4EFFC; }
.b-wait { color:var(--orange); border-color:var(--orange); background:#FFF4E6; }
.b-done { color:var(--muted); border-color:var(--line2); background:#F4F6F8; }
.b-err { color:var(--red); border-color:var(--red); background:#FDF1F0; }
.b-acc { color:var(--blue); border-color:var(--blue); background:#EEF4FA; }

/* ---- 空态 ---- */
.empty { border:1.5px dashed var(--line2); border-radius:10px; padding:34px 22px;
  text-align:center; background:var(--card); }
.empty-icon svg { width:46px; height:46px; }
.empty-title { font-size:15px; font-weight:700; color:var(--ink); margin:12px 0 6px;
  font-family:var(--mono); }
.empty-reason { font-size:12.5px; color:var(--muted); margin-bottom:12px; line-height:1.7;
  font-family:var(--mono); }
.empty-action { font-family:var(--mono); font-size:12px; color:var(--blue); }

/* ---- 比赛行 ---- */
.mcard { display:flex; align-items:stretch; background:var(--card); border:1px solid var(--line);
  border-radius:12px; margin-bottom:10px; overflow:hidden; box-shadow:var(--shadow);
  transition:all .18s ease-out; }
.mcard:hover { box-shadow:var(--shadow-hover); transform:translateY(-1px); }
.mcard-date { width:74px; flex:0 0 auto; background:var(--blue); color:#fff;
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  font-family:var(--mono); font-weight:700; gap:2px; }
.mcard-date .d { font-size:22px; line-height:1; }
.mcard-date .m { font-size:10px; letter-spacing:1.6px; opacity:.85; }
.mcard-main { flex:1; padding:13px 16px; min-width:0; }
.mcard-head { display:flex; align-items:center; gap:10px; font-size:10.5px; color:var(--muted);
  margin-bottom:9px; flex-wrap:wrap; font-family:var(--mono); }
.mcard-foot { display:flex; gap:18px; margin-top:9px; font-size:11px; color:var(--muted);
  font-family:var(--mono); }
.mcard-foot .ok { color:var(--teal); font-weight:700; }

/* ---- 选手 ---- */
.pgrid { display:grid; grid-template-columns:repeat(auto-fill,minmax(252px,1fr)); gap:10px; }
.pcard { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:13px 15px;
  border-left:4px solid var(--blue); box-shadow:var(--shadow); transition:all .18s ease-out; }
.pcard:hover { box-shadow:var(--shadow-hover); transform:translateY(-1px); }
.pcard-top { display:flex; align-items:center; gap:8px; font-size:13px; font-weight:700;
  color:var(--ink); font-family:var(--mono); }
.pcard-pos { margin-left:auto; font-size:9.5px; color:var(--muted); font-weight:400;
  letter-spacing:1.2px; text-transform:uppercase; }
.mvp { font-size:9px; font-weight:700; color:#fff; background:var(--orange);
  border-radius:4px; padding:1.5px 6px; letter-spacing:1px; }
.mvp.lose { background:var(--muted); }
.pcard-hero { font-size:11.5px; color:var(--blue); margin:6px 0 8px; font-family:var(--mono); }
.pcard-meta { display:flex; gap:16px; font-family:var(--mono); font-size:11px; color:var(--ink2); }

.lb-row { display:flex; align-items:center; gap:14px; background:var(--card); border:1px solid var(--line);
  border-radius:10px; padding:11px 15px; margin-bottom:9px; box-shadow:var(--shadow);
  transition:all .18s ease-out; }
.lb-row:hover { box-shadow:var(--shadow-hover); transform:translateX(3px); }
.lb-rank { width:38px; height:38px; flex:0 0 auto; display:flex; align-items:center;
  justify-content:center; font-family:var(--mono); font-weight:700; font-size:16px;
  background:var(--ink); color:#fff; border-radius:8px; }
.lb-rank.r1 { background:var(--orange); } .lb-rank.r2 { background:var(--blue); }
.lb-rank.r3 { background:var(--teal); }
.lb-main { flex:1; min-width:0; }
.lb-name { font-family:var(--mono); font-size:13.5px; font-weight:700; color:var(--ink); }
.lb-sub { font-family:var(--mono); font-size:10.5px; color:var(--muted); margin-top:3px; }
.lb-value { font-family:var(--mono); font-size:23px; font-weight:700; color:var(--blue);
  letter-spacing:-.02em; }

/* ---- BP ---- */
.bp-grid { width:100%; border-collapse:collapse; background:var(--card); }
.bp-grid td { padding:7px 10px; border-bottom:1px solid var(--line);
  font-size:12.5px; vertical-align:middle; font-family:var(--mono); }
.bp-grid tr:hover td { background:var(--row-hover); }
.bp-grid .bp-phase { color:var(--muted); font-size:10px; width:84px; font-weight:700;
  text-transform:uppercase; letter-spacing:.8px; }
.bp-hero { display:inline-block; border-radius:5px; padding:2.5px 9px; margin:1px 4px 1px 0;
  font-size:12px; font-family:var(--mono); }
.bp-pick { color:var(--blue); background:#EEF4FA; border:1px solid #C9DCF0; }
.bp-ban { color:var(--muted); background:#F4F6F8; border:1px solid var(--line);
  text-decoration:line-through; text-decoration-color:rgba(192,57,43,.7); }
.roster { display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin-top:8px; }
.roster-cell { background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:10px 6px; text-align:center; box-shadow:var(--shadow); }
.roster-pos { font-size:9px; color:var(--muted); letter-spacing:1.2px; text-transform:uppercase;
  font-family:var(--mono); }
.roster-hero { font-size:12.5px; color:var(--ink); font-weight:700; margin-top:3px;
  font-family:var(--mono); }

/* ---- 状态灯 ---- */
.light-row { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:16px; }
.light { flex:1; min-width:170px; background:var(--card); border:1px solid var(--line);
  border-radius:10px; padding:13px 15px; border-top:4px solid var(--line2); box-shadow:var(--shadow);
  transition:all .18s ease-out; }
.light:hover { box-shadow:var(--shadow-hover); }
.light-name { font-size:10px; color:var(--muted); margin-bottom:7px; letter-spacing:1.2px;
  text-transform:uppercase; font-family:var(--mono); }
.light-state { font-size:16px; font-weight:700; font-family:var(--mono); }
.light-sub { font-size:10.5px; color:var(--muted); margin-top:5px; font-family:var(--mono); }
.light .ls-on { color:var(--teal); } .light .ls-warn { color:var(--orange); }
.light .ls-off { color:var(--muted); } .light .ls-err { color:var(--red); }
.light.ls-live { border-top-color:var(--teal); } .light.ls-warn { border-top-color:var(--orange); }
.light.ls-err { border-top-color:var(--red); }

.note-line { font-size:11px; color:var(--muted); margin-top:6px; line-height:1.7;
  font-family:var(--mono); }
.mono { font-family:var(--mono); }

/* ---- 行内图标 ---- */
.timg { width:34px; height:34px; border-radius:8px; object-fit:cover; flex:0 0 auto;
  display:inline-block; vertical-align:middle; background:rgba(120,130,145,.12);
  box-shadow:inset 0 0 0 1px var(--line); }
.timg.sm { width:24px; height:24px; border-radius:6px; }
.timg.xs { width:18px; height:18px; border-radius:5px; }
.timg.round { border-radius:50%; }
.lead { display:flex; align-items:center; gap:9px; min-width:0; }
.lead .nm { font-weight:600; color:var(--ink); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.lead .nm .sub { display:block; font-size:10px; font-weight:400; color:var(--muted); }

/* ---- 迷你比例条 ---- */
.mini-bar { display:inline-flex; align-items:center; gap:7px; min-width:96px; }
.mini-bar .track { width:74px; height:6px; border-radius:4px; background:var(--head-bg);
  overflow:hidden; position:relative; }
.mini-bar .fill { height:100%; border-radius:4px; }
.mini-bar .val { font-family:var(--mono); font-size:11px; color:var(--ink2);
  font-variant-numeric:tabular-nums; min-width:34px; text-align:right; }

/* ---- 档位徽章 ---- */
.tier { display:inline-flex; align-items:center; justify-content:center; min-width:22px; height:22px;
  border-radius:6px; font-family:var(--mono); font-size:12px; font-weight:700; color:#fff; }
.tier.S { background:var(--orange); } .tier.A { background:var(--teal); }
.tier.B { background:var(--blue); } .tier.C { background:var(--muted); }

/* ---- 紧凑数据表 ---- */
.pt { width:100%; border-collapse:collapse; background:var(--card);
  border:1px solid var(--line); border-radius:10px; overflow:hidden; box-shadow:var(--shadow);
  font-size:12.5px; }
.pt thead th { background:var(--head-bg); color:var(--ink2); font-family:var(--mono);
  font-size:10px; letter-spacing:1.1px; text-transform:uppercase; text-align:left;
  padding:8px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }
.pt thead th.num, .pt tbody td.num { text-align:right; }
.pt tbody td { padding:7px 12px; border-bottom:1px solid var(--line); vertical-align:middle;
  color:var(--ink); font-variant-numeric:tabular-nums; }
.pt tbody tr:last-child td { border-bottom:none; }
.pt tbody tr:hover td { background:var(--row-hover); }
.pt td.num { font-family:var(--mono); }
.pt .sub { color:var(--muted); font-size:11px; }
.pt .strong { font-family:var(--mono); font-weight:700; }

/* ---- 对阵对比表（kplll 风格） ---- */
.compare { display:grid; grid-template-columns:1fr 90px 1fr; background:var(--card);
  border:1px solid var(--line); border-radius:12px; overflow:hidden; box-shadow:var(--shadow);
  margin-bottom:14px; }
.cmp-team { padding:14px 16px; display:flex; flex-direction:column; gap:8px; min-width:0; }
.cmp-team .head { display:flex; align-items:center; gap:10px; }
.cmp-team .nm { font-family:var(--mono); font-weight:700; font-size:15px; color:var(--ink);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.cmp-mid { background:var(--ink); color:#fff; display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:6px; padding:10px 4px; }
.cmp-mid .vs { font-family:var(--mono); font-weight:700; letter-spacing:2px; font-size:14px; }
.cmp-mid .score { font-family:var(--mono); font-size:26px; font-weight:700; line-height:1; }
.cmp-mid .sub { font-size:9.5px; color:rgba(255,255,255,.72); font-family:var(--mono); }
.cmp-rows { display:grid; gap:1px; background:var(--line); border-top:1px solid var(--line); }
.cmp-row { display:grid; grid-template-columns:1fr 90px 1fr; background:var(--card);
  font-size:12px; align-items:center; }
.cmp-row > span { padding:5px 16px; font-family:var(--mono); }
.cmp-row .k { grid-column:2; text-align:center; color:var(--muted); font-size:10px;
  letter-spacing:1.2px; text-transform:uppercase; }
.cmp-row .vl { text-align:right; color:var(--ink); font-weight:700; }
.cmp-row .vr { text-align:left; color:var(--ink); font-weight:700; }
.cmp-row .hl { text-align:right; color:var(--blue); }
.cmp-row .hr { text-align:left; color:var(--red); }

/* ---- 比赛行 ---- */
.m-row { display:grid; grid-template-columns:96px 1fr 72px 1fr 120px; gap:12px; align-items:center;
  background:var(--card); border:1px solid var(--line); border-left:3px solid var(--blue);
  border-radius:10px; padding:10px 14px; margin-bottom:8px; box-shadow:var(--shadow);
  transition:all .18s ease-out; }
.m-row:hover { box-shadow:var(--shadow-hover); transform:translateY(-1px); }
.m-row .dt { font-family:var(--mono); font-size:11px; color:var(--muted); line-height:1.5; }
.m-row .dt b { display:block; font-size:13px; color:var(--ink); }
.m-row .tm { display:flex; align-items:center; gap:9px; font-family:var(--mono);
  font-weight:700; font-size:13px; color:var(--ink); min-width:0; }
.m-row .tm.r { flex-direction:row-reverse; text-align:right; }
.m-row .sc { text-align:center; font-family:var(--mono); font-size:17px; font-weight:700;
  color:var(--ink); }
.m-row .sc .bo { display:block; font-size:9.5px; color:var(--muted); font-weight:400; }
.m-row .act { display:flex; flex-direction:column; gap:5px; align-items:flex-end; }
.m-row .meta { font-family:var(--mono); font-size:10px; color:var(--muted); }

/* ---- 紧凑统计条 ---- */
.stat-strip { display:grid; gap:10px; margin-bottom:14px; }
.scell { background:var(--card); border:1px solid var(--line); border-top:2px solid var(--blue);
  border-radius:8px; padding:9px 14px; }
.scell .k { font-size:9px; letter-spacing:1.2px; text-transform:uppercase; color:var(--muted);
  font-family:var(--mono); }
.scell .v { font-family:var(--mono); font-size:19px; font-weight:700; color:var(--ink);
  line-height:1.2; }
.scell .n { font-size:10px; color:var(--muted); font-family:var(--mono); }

.panel .strip { display:flex; gap:10px; flex-wrap:wrap; }
.strip .cell { background:var(--bg); border:1px solid var(--line); border-radius:8px;
  padding:7px 12px; font-family:var(--mono); font-size:11.5px; color:var(--ink2); }
.strip .cell b { color:var(--ink); font-size:14px; margin-right:4px; }

/* ---- 深色覆盖 ---- */
.mu-blue { background:linear-gradient(180deg,#F2F7FB,#EAF2F9); border-right:1px solid var(--line); }
.mu-red { background:linear-gradient(180deg,#FBF3F2,#F8ECEA); text-align:right; }
.bp-pick { color:var(--blue); background:rgba(0,86,145,.09); border:1px solid rgba(0,86,145,.28); }
.bp-ban { color:var(--muted); background:var(--bg); border:1px solid var(--line); }
[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child {
  background:var(--card); }
.fade-up { animation:fadeUp .42s ease-out both; }
@keyframes fadeUp { from { opacity:0; transform:translateY(16px);} to { opacity:1; transform:none;} }
::-webkit-scrollbar { width:9px; height:9px; }
::-webkit-scrollbar-thumb { background:var(--line2); border-radius:6px; }
::-webkit-scrollbar-track { background:transparent; }
"""


# ---------------- 组件 ----------------
def src_tag(kind: str = "官方", title: str = "") -> str:
    color, bg = SRC_STYLES.get(kind, (MUTED, "#F1F3F5"))
    tip = f' title="{html.escape(title)}"' if title else ""
    return f'<span class="stg"{tip} style="color:{color};background:{bg};border-color:{color};">{kind}</span>'


def badge(state: str, label: str | None = None) -> str:
    state = str(state or "")
    cls_map = {
        "live": "b-live", "LIVE": "b-live", "进行中": "b-live",
        "stale": "b-wait", "waiting_start": "b-wait", "未开始": "b-wait",
        "clean": "b-clean", "day_complete": "b-clean", "done": "b-clean", "已结束": "b-done",
        "quarantine": "b-quar", "error": "b-err", "异常": "b-err",
        "ready": "b-clean", "估算": "b-acc", "官方": "b-acc", "代理": "b-wait",
    }
    text_map = {
        "live": "LIVE", "waiting_start": "等待开赛", "day_complete": "当日完成",
        "clean": "CLEAN", "quarantine": "QUARANTINE", "stale": "STALE",
        "error": "异常", "ready": "READY", "done": "DONE", "未开始": "未开始",
        "进行中": "进行中", "已结束": "已结束",
    }
    text = label or text_map.get(state, state)
    cls = cls_map.get(state, cls_map.get(text, "b-wait"))
    return f'<span class="bdg {cls}">{html.escape(str(text))}</span>'


def metric_card(label: str, value: object, source: str | None = None, note: str = "",
                tone: str | None = None, delta: str | None = None, src_title: str = "",
                bar: str = "blue") -> str:
    tag = src_tag(source, src_title) if source else ""
    delta_html = f'<div class="kpi-delta">{delta}</div>' if delta else ""
    tone_cls = {"up": "t-up", "down": "t-down", "warn": "t-warn", "acc": "t-acc"}.get(tone or "", "")
    note_html = f'<div class="kpi-note">{note}</div>' if note else ""
    bar_cls = f" bar-{bar}" if bar in ("orange", "purple", "teal", "red", "blue") else ""
    return (
        f'<div class="kpi{bar_cls}"><div class="kpi-top"><span class="kpi-label">{_esc(label)}</span>{tag}</div>'
        f'<div class="kpi-value {tone_cls}">{_esc(value)}</div>{delta_html}{note_html}</div>'
    )


def stat_row(blocks: list[str], cols: str = "1.4fr 1fr 1fr 1fr") -> str:
    return f'<div class="stat-row" style="grid-template-columns:{cols}">{"".join(blocks)}</div>'


def stat_strip(items: list[tuple[str, str, str]], cols: str = "1fr 1fr 1fr 1fr") -> str:
    inner = "".join(
        f'<div class="scell"><div class="k">{_esc(k)}</div><div class="v">{v}</div>'
        f'<div class="n">{_esc(n)}</div></div>' for k, v, n in items)
    return f'<div class="stat-strip" style="grid-template-columns:{cols}">{inner}</div>'


def matchup_bar(t1: str, t2: str, p1: float | None = None, score1: object = None,
                score2: object = None, winner: str | None = None, sub: str = "") -> str:
    t1s, t2s = _esc(t1), _esc(t2)
    p1v = 0.5 if p1 is None else float(np.clip(p1, 0.02, 0.98))
    pct = p1v * 100
    s1 = _esc(score1 if score1 is not None else "—")
    s2 = _esc(score2 if score2 is not None else "—")
    win1 = " mu-win" if (winner and str(winner) == str(t1)) else ""
    win2 = " mu-win" if (winner and str(winner) == str(t2)) else ""
    tag1 = '<span class="mu-tag">WIN</span>' if win1 else ""
    tag2 = '<span class="mu-tag">WIN</span>' if win2 else ""
    sub_html = f'<div class="mu-sub">{sub}</div>' if sub else ""
    return (
        f'<div class="matchup">'
        f'<div class="mu-team mu-blue{win1}"><div class="mu-head"><span class="mu-name">{t1s}</span>{tag1}</div>'
        f'<div class="mu-score">{s1}</div><div class="mu-pct" style="color:{BLUE}">{p1v:.1%}</div></div>'
        f'<div class="mu-center"><div class="mu-vs">VS</div>'
        f'<div class="mu-split"><div class="mu-fill" style="width:{pct:.1f}%;background:{BLUE}"></div></div>'
        f'{sub_html}</div>'
        f'<div class="mu-team mu-red{win2}"><div class="mu-head">{tag2}<span class="mu-name">{t2s}</span></div>'
        f'<div class="mu-score">{s2}</div><div class="mu-pct" style="color:{RED}">{1 - p1v:.1%}</div></div>'
        f'</div>'
    )


def matchup_compare_html(c1: str, c2: str, p1: float | None = None,
                         score1: object = None, score2: object = None,
                         sub: str = "", icon1: str = "", icon2: str = "",
                         mid_label: str = "VS") -> str:
    p1v = 0.5 if p1 is None else float(np.clip(p1, 0.02, 0.98))
    s1 = _esc(score1 if score1 is not None else "—")
    s2 = _esc(score2 if score2 is not None else "—")
    cmp_rows = "".join([
        f'<div class="cmp-row"><span class="vl hl">{p1v:.1%}</span>'
        f'<span class="k">蓝方胜率</span><span class="vr hr">{1 - p1v:.1%}</span></div>',
        f'<div class="cmp-row"><span class="vl">{p1v * 100:.0f}</span>'
        f'<span class="k">优势指数</span><span class="vr">{(1 - p1v) * 100:.0f}</span></div>',
    ])
    sub_html = f'<div class="sub">{_esc(sub)}</div>' if sub else '<div class="sub">&nbsp;</div>'
    return (
        f'<div class="compare">'
        f'<div class="cmp-team"><div class="head">{img_tag(icon1, size="sm")}'
        f'<span class="nm">{_esc(c1)}</span></div></div>'
        f'<div class="cmp-mid"><span class="vs">{mid_label}</span>'
        f'<div class="score">{s1}:{s2}</div>{sub_html}</div>'
        f'<div class="cmp-team"><div class="head" style="justify-content:flex-end;text-align:right">'
        f'<span class="nm">{_esc(c2)}</span>{img_tag(icon2, size="sm")}</div></div>'
        f'<div class="cmp-rows">{cmp_rows}</div></div>')


def section_head(title: str, subtitle: str = "", right: str = "", tag: str = "",
                 kicker: str = "KPL DATA CENTER") -> str:
    tag_html = f'<span class="inline-tag">{tag}</span>' if tag else ""
    kicker_html = f'<div class="page-kicker">{_esc(kicker)}</div>' if kicker else ""
    return (
        f'<div class="page-head"><div>{kicker_html}'
        f'<div class="page-title">{_esc(title)}{tag_html}</div>'
        f'<div class="page-sub">{_esc(subtitle)}</div></div>'
        f'<div class="page-right">{right}</div></div>'
    )


def empty_state(title: str, reason: str, action: str = "") -> str:
    action_html = f'<div class="empty-action">{_esc(action)}</div>' if action else ""
    icon = (
        '<svg viewBox="0 0 48 48" fill="none" stroke="#B8C2CC" stroke-width="2">'
        '<rect x="6" y="6" width="14" height="14"/>'
        '<rect x="28" y="6" width="14" height="14" transform="rotate(45 35 13)" stroke="#FF8C00"/>'
        '<rect x="6" y="28" width="14" height="14" transform="rotate(45 13 35)" stroke="#005691"/>'
        '<rect x="28" y="28" width="14" height="14"/>'
        '</svg>'
    )
    return (
        f'<div class="empty"><div class="empty-icon">{icon}</div>'
        f'<div class="empty-title">{_esc(title)}</div>'
        f'<div class="empty-reason">{_esc(reason)}</div>{action_html}</div>'
    )


def panel_html(title: str = "", source: str | None = None, body: str = "", sunken: bool = False,
               src_title: str = "") -> str:
    cls = " panel-sunken" if sunken else ""
    tag = src_tag(source, src_title) if source else ""
    head = f'<div class="panel-title">{_esc(title)}{tag}</div>' if title else ""
    return f'<div class="panel{cls}">{head}{body}</div>'


def leaderboard_rows(rows: list[dict]) -> str:
    parts = []
    for r in rows:
        rank = int(r.get("rank", 0))
        rank_cls = f" r{rank}" if rank <= 3 else ""
        color = r.get("color") or BLUE
        parts.append(
            f'<div class="lb-row"><div class="lb-rank{rank_cls}">{rank}</div>'
            f'<div class="lb-main"><div class="lb-name">{_esc(r.get("name", ""))}</div>'
            f'<div class="lb-sub">{_esc(r.get("sub", ""))}</div></div>'
            f'<div class="lb-value" style="color:{color}">{_esc(r.get("value", ""))}</div></div>')
    return "".join(parts)


def img_tag(url: object, size: str = "", round_: bool = False, alt: str = "") -> str:
    if url is None or pd.isna(url) or not str(url).strip():
        return ""
    size_cls = {"sm": " sm", "xs": " xs"}.get(size, "")
    round_cls = " round" if round_ else ""
    esc = html.escape
    return (f'<img class="timg{size_cls}{round_cls}" src="{esc(str(url))}" '
            f'alt="{esc(alt)}" loading="lazy" '
            f'onerror="this.style.visibility=\'hidden\'">')


def mini_bar(pct: object, color: str = "var(--blue)", digits: int = 1, suffix: str = "%") -> str:
    try:
        v = 0.0 if pct is None or pd.isna(pct) else float(pct)
    except (TypeError, ValueError):
        v = 0.0
    v = min(max(v, 0.0), 100.0)
    return (f'<span class="mini-bar"><span class="track">'
            f'<span class="fill" style="width:{v:.1f}%;background:{color}"></span></span>'
            f'<span class="val">{v:.{digits}f}{suffix}</span></span>')


def tier_badge(rate: object) -> str:
    try:
        v = float(rate)
    except (TypeError, ValueError):
        return ""
    tier = "S" if v >= 0.55 else ("A" if v >= 0.50 else ("B" if v >= 0.45 else "C"))
    return f'<span class="tier {tier}">{tier}</span>'


def lead_cell(icon: object, name: object, sub: str = "", size: str = "sm",
              round_: bool = False) -> str:
    sub_html = f'<span class="sub">{_esc(sub)}</span>' if sub else ""
    return (f'<span class="lead">{img_tag(icon, size=size, round_=round_) }'
            f'<span class="nm">{_esc(name)}{sub_html}</span></span>')


def pt_table(headers: list[str], rows: list[list[str]],
             num_cols: set[int] | None = None, empty: str = "暂无数据") -> str:
    num_cols = num_cols or set()
    if not rows:
        return empty_state("暂无数据", empty)
    head = "<tr>" + "".join(
        f'<th{" class=\"num\"" if i in num_cols else ""}>{_esc(h)}</th>'
        for i, h in enumerate(headers)) + "</tr>"
    body = []
    for r in rows:
        tds = []
        for i, v in enumerate(r):
            cls = ' class="num"' if i in num_cols else ""
            tds.append(f"<td{cls}>{v}</td>")
        body.append(f"<tr>{''.join(tds)}</tr>")
    return f'<table class="pt"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


@st.cache_data(ttl=600, show_spinner=False)
def icon_maps() -> tuple[dict[str, str], dict[str, str]]:
    team_ic: dict[str, str] = {}
    hero_ic: dict[str, str] = {}
    p = PROCESSED_DIR / "players.csv"
    if p.exists():
        try:
            df = pd.read_csv(p, usecols=["team_name", "team_icon", "hero_name", "hero_icon"],
                             low_memory=False)
            for t, i in df[["team_name", "team_icon"]].dropna().itertuples(index=False):
                team_ic.setdefault(str(t), str(i))
            for h, i in df[["hero_name", "hero_icon"]].dropna().itertuples(index=False):
                hero_ic.setdefault(str(h), str(i))
        except (OSError, pd.errors.ParserError, ValueError):
            pass
    return team_ic, hero_ic


def team_icon(team: str) -> str:
    tm, _ = icon_maps()
    return tm.get(str(team), "")


def hero_icon(hero: str) -> str:
    _, hm = icon_maps()
    return hm.get(str(hero), "")


def ctx_bar(chips: list[tuple[str, str]]) -> str:
    inner = '<span class="ctx-label">CONTEXT</span>' + "".join(
        f'<span class="ctx-chip">{_esc(k)} <b>{_esc(v)}</b></span>' for k, v in chips)
    return f'<div class="ctx-bar">{inner}</div>'


# ---------------- 图表库 ----------------
def is_dark() -> bool:
    return bool(st.session_state.get("dark_mode", False))


def chart_theme(fig: go.Figure, height: int = 380, title: str = "") -> go.Figure:
    dark = is_dark()
    plot_bg = "#10161E" if dark else "#FFFFFF"
    grid = "rgba(148,163,184,0.14)" if dark else "rgba(31,41,55,0.07)"
    axis_line = "#303A46" if dark else LINE
    tick = "#9AA5B1" if dark else INK_2
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=44, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=plot_bg,
        font=dict(family=MONO, color=tick, size=11),
        hoverlabel=dict(bgcolor=INK, bordercolor=INK, font_color="#FFFFFF",
                        font=dict(family=MONO, size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=10.5)),
        title=dict(text=title, font=dict(size=13, color=INK if not dark else "#E8EDF3", family=MONO),
                   x=0, xanchor="left"),
        showlegend=True,
        bargap=0.35,
    )
    fig.update_xaxes(gridcolor=grid, zeroline=False,
                     linecolor=axis_line, tickfont=dict(size=10.5, family=MONO, color=tick))
    fig.update_yaxes(gridcolor=grid, zeroline=True,
                     zerolinecolor=axis_line, tickfont=dict(size=10.5, family=MONO, color=tick))
    return fig


def _grad(color: str, alpha: float = 0.26) -> dict:
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return dict(type="vertical", colorscale=[
        (0.0, "rgba(255,255,255,0)"),
        (1.0, f"rgba({r},{g},{b},{alpha})"),
    ])


def phase_bands(fig: go.Figure, xmin: float, xmax: float) -> None:
    bands = [
        (1, 8, "EARLY 1–8′", "rgba(32,178,170,0.05)", TEAL),
        (8, 15, "MID 9–15′", "rgba(255,140,0,0.05)", ORANGE),
        (15, max(xmax, 16), "LATE 16′+", "rgba(139,43,226,0.05)", PURPLE),
    ]
    for x0, x1, label, fill, color in bands:
        if x1 <= xmin:
            continue
        fig.add_vrect(x0=max(x0, xmin), x1=min(x1, xmax), fillcolor=fill, line_width=0)
        fig.add_annotation(x=min(max((x0 + x1) / 2, xmin + 0.3), xmax - 0.3), y=1.035,
                           text=label, showarrow=False, font=dict(size=8.5, color=color, family=MONO),
                           xref="x", yref="paper")


def winrate_chart(df: pd.DataFrame, events: list | None = None, turns: list | None = None,
                  teams: tuple[str, str] | None = None, height: int = 440,
                  title: str = "胜率时间序列 · V11（估算）") -> go.Figure:
    c1, c2 = teams or ("蓝方", "红方")
    x = df["minute"].astype(float)
    p1 = df["p_v11"]
    p2 = 1 - p1
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=p2, mode="lines", line=dict(color=RED, width=1.2),
        fill="tozeroy", fillgradient=_grad(RED, 0.18), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=x, y=p1, mode="lines", line=dict(color=BLUE, width=1.2),
        fill="tozeroy", fillgradient=_grad(BLUE, 0.22), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=x, y=p2, mode="lines", name=c2, line=dict(color=RED, width=2.8),
        hovertemplate=f"{_esc(c2)} %{{y:.1%}}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=x, y=p1, mode="lines", name=c1, line=dict(color=BLUE, width=2.8),
        hovertemplate=f"{_esc(c1)} %{{y:.1%}}<extra></extra>"))
    phase_bands(fig, float(x.min()), float(x.max()))
    fig.add_hline(y=0.5, line_dash="dot", line_color="rgba(31,41,55,0.5)", line_width=1)
    for ev in events or []:
        m = float(ev.get("minute", 0) or 0)
        team = str(ev.get("team") or "")
        color = BLUE if team == c1 else (RED if team == c2 else TEAL)
        fig.add_trace(go.Scatter(
            x=[m], y=[0.995], mode="markers",
            marker=dict(symbol="diamond", size=9, color=color, line=dict(color="#fff", width=1)),
            name=ev.get("label") or ev.get("type") or "",
            hovertemplate=f"{_esc(ev.get('label') or '')} @ %{{x:.1f}}′<extra></extra>",
            showlegend=False))
    for t in turns or []:
        m = float(t["minute"])
        fig.add_vline(x=m, line_dash="dash", line_color=ORANGE, line_width=1.4)
        fig.add_annotation(x=m, y=0.02, text=f"{t['delta']:+.0%}", showarrow=False,
                           font=dict(size=9.5, color=ORANGE_D, family=MONO))
    last = len(x) - 1
    fig.add_trace(go.Scatter(
        x=[x.iloc[last]], y=[p1.iloc[last]], mode="markers",
        marker=dict(symbol="circle", size=13, color=BLUE,
                    line=dict(color="#fff", width=3)),
        name="当前", hovertemplate=f"{_esc(c1)} %{{y:.1%}} · 当前<extra></extra>",
        showlegend=False))
    fig.update_yaxes(range=[0, 1], tickformat=".0%")
    fig.update_xaxes(title=dict(text="比赛分钟", font=dict(size=10)))
    fig.update_layout(hovermode="x unified", clickmode="event+select")
    return chart_theme(fig, height=height, title=title)


def economy_chart(df: pd.DataFrame, height: int = 210, title: str = "经济差 · 蓝方为正（官方）") -> go.Figure:
    x = df["minute"].astype(float)
    gd = pd.to_numeric(df["gold_diff"], errors="coerce").fillna(0.0)
    colors = [TEAL if v >= 0 else RED for v in gd]
    fig = go.Figure(go.Bar(
        x=x, y=gd, marker_color=colors, marker_line_width=0,
        hovertemplate="%{x:.1f}′ · %{y:+,.0f}<extra></extra>"))
    fig.add_hline(y=0, line_color="rgba(31,41,55,0.35)", line_width=1)
    fig.update_yaxes(tickformat="+,.0f")
    fig.update_xaxes(title=dict(text="比赛分钟", font=dict(size=10)))
    return chart_theme(fig, height=height, title=title)


def benchmark_chart(df: pd.DataFrame, height: int = 330) -> go.Figure:
    x = df["minute"].astype(float)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=df["p_gold"], name="金差先验（代理）",
                             line=dict(color=LINE_2, width=1.8, dash="dot")))
    fig.add_trace(go.Scatter(x=x, y=df["p_v11"], name="平台胜率（估算）",
                             line=dict(color=BLUE, width=2.8),
                             fill="tozeroy", fillgradient=_grad(BLUE, 0.12)))
    guard = df[df["gold_guard_applied"].astype(bool)] if "gold_guard_applied" in df else pd.DataFrame()
    if not guard.empty:
        fig.add_trace(go.Scatter(x=guard["minute"].astype(float), y=guard["p_v11"],
                                 name="护栏生效", mode="markers",
                                 marker=dict(color=ORANGE, size=9, symbol="diamond",
                                             line=dict(color="#fff", width=1))))
    fig.add_hline(y=0.5, line_dash="dot", line_color="rgba(31,41,55,0.5)")
    fig.update_yaxes(range=[0, 1], tickformat=".0%")
    fig.update_xaxes(title=dict(text="比赛分钟", font=dict(size=10)))
    fig.update_layout(hovermode="x unified")
    return chart_theme(fig, height=height, title="平台胜率 vs 金差先验（P07）")


def lane_chart(frames: list[dict], height: int = 300) -> go.Figure:
    lane_cols = [("gold_diff_top", "对抗路", ORANGE), ("gold_diff_jungle", "打野", PURPLE),
                 ("gold_diff_mid", "中路", TEAL), ("gold_diff_adc", "发育路", BLUE),
                 ("gold_diff_support", "游走", LINE_2)]
    fig = go.Figure()
    for col, name, color in lane_cols:
        y = [float(f.get(col, 0) or 0) for f in frames]
        fig.add_trace(go.Scatter(
            x=[float(f.get("minute", 0) or 0) for f in frames], y=y, name=name,
            line=dict(color=color, width=2), hovertemplate="%{y:+,.0f}<extra></extra>"))
    fig.add_hline(y=0, line_color="rgba(31,41,55,0.30)")
    fig.update_yaxes(tickformat="+,.0f")
    fig.update_xaxes(title=dict(text="比赛分钟", font=dict(size=10)))
    return chart_theme(fig, height=height, title="分路经济差（官方）")


def radar_chart(values: dict[str, float], team: str, height: int = 300) -> go.Figure:
    labels = list(values.keys())
    vals = [float(values[k]) for k in labels]
    color = team_color(team)
    fig = go.Figure(go.Scatterpolar(
        r=vals + [vals[0]], theta=labels + [labels[0]], fill="toself",
        fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.20)",
        line=dict(color=color, width=2.4)))
    fig.update_layout(
        polar=dict(bgcolor="rgba(255,255,255,0)",
                   radialaxis=dict(visible=True, range=[0, 1], gridcolor="rgba(31,41,55,0.14)",
                                   tickfont=dict(size=9))),
        showlegend=False)
    return chart_theme(fig, height=height, title=f"{team} · 风格雷达（代理）")


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str, height: int = 280,
              color: str = ORANGE, yfmt: str | None = None) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=df[x], y=df[y], marker_color=color, marker_line_width=0,
        text=df[y].map(lambda v: f"{v:,.0f}" if yfmt == "int" else f"{v:.1%}"),
        textposition="outside", textfont=dict(size=10.5, color=INK, family=MONO),
        hovertemplate="%{y:,}<extra></extra>" if yfmt == "int" else "%{y:.1%}<extra></extra>"))
    fig.update_layout(xaxis=dict(type="category"))
    if yfmt == "pct":
        fig.update_yaxes(tickformat=".0%")
    return chart_theme(fig, height=height, title=title)


def hero_scatter(df: pd.DataFrame, height: int = 400) -> go.Figure:
    pos_colors = {"对抗路": ORANGE, "打野": PURPLE, "中路": TEAL,
                  "发育路": BLUE, "游走": LINE_2, "—": LINE_2}
    fig = go.Figure()
    for pos in df["主位置"].dropna().unique():
        sub = df[df["主位置"] == pos]
        fig.add_trace(go.Scatter(
            x=sub["pick率"], y=sub["胜率"], mode="markers", name=str(pos),
            marker=dict(size=np.clip(sub["出场"] / sub["出场"].max() * 26 + 8, 9, 34),
                        color=pos_colors.get(str(pos), BLUE), opacity=0.82,
                        line=dict(color="#fff", width=1.5)),
            error_y=dict(type="data", array=(sub["ci_hi"] - sub["胜率"]),
                         arrayminus=(sub["胜率"] - sub["ci_lo"]), visible=True,
                         thickness=1, width=2, color="rgba(31,41,55,0.35)"),
            customdata=sub[["英雄", "出场"]],
            hovertemplate="%{customdata[0]}<br>出场 %{customdata[1]}<br>"
                          "pick %{x:.1%} · 胜率 %{y:.1%}<extra></extra>"))
    fig.add_hline(y=0.5, line_dash="dot", line_color="rgba(31,41,55,0.5)")
    fig.update_xaxes(title=dict(text="出场率（pick）", font=dict(size=10)), tickformat=".0%")
    fig.update_yaxes(title=dict(text="胜率（Wilson CI）", font=dict(size=10)), tickformat=".0%")
    return chart_theme(fig, height=height, title="英雄 Meta · 出场率 × 胜率")


def coverage_chart(matches: pd.DataFrame, battles: pd.DataFrame, height: int = 260) -> go.Figure:
    dates = sorted(matches["date"].dropna().astype(str).unique())
    total = matches.groupby("date").size().reindex(dates, fill_value=0)
    cov = battles.groupby("date").size().reindex(dates, fill_value=0)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=dates, y=total, name="归档大场", marker_color="#D9E2EC",
                         hovertemplate="%{x}<br>归档 %{y} 场<extra></extra>"))
    fig.add_trace(go.Bar(x=dates, y=cov, name="已采集", marker_color=BLUE,
                         hovertemplate="%{x}<br>已采集 %{y} 场<extra></extra>"))
    fig.update_layout(barmode="group", xaxis=dict(type="category", tickangle=-55))
    return chart_theme(fig, height=height, title="按日期的覆盖分布（官方）")


def data_table(df: pd.DataFrame, height: int | None = None) -> None:
    if df is None or df.empty:
        st.markdown(empty_state("暂无数据", "当前筛选下没有可用记录。"), unsafe_allow_html=True)
        return
    cfg: dict[str, object] = {}
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            cfg[c] = st.column_config.NumberColumn(c, format="%,.1f")
    kwargs: dict[str, object] = {"hide_index": True, "width": "stretch", "column_config": cfg}
    if height is not None:
        kwargs["height"] = height
    st.dataframe(df, **kwargs)


# ---------------- 数据层 ----------------
@st.cache_data(ttl=300, show_spinner=False)
def load_tables() -> dict[str, pd.DataFrame]:
    out = {}
    for name in ["matches", "battles", "teams", "events"]:
        p = ANALYSIS_DIR / f"{name}.csv"
        df = pd.read_csv(p) if p.exists() else pd.DataFrame()
        if not df.empty:
            for col in ("match_id", "battle_id"):
                if col in df.columns:
                    df[col] = df[col].astype(str)
        out[name] = df
    return out


@st.cache_data(ttl=120, show_spinner=False)
def load_archive() -> pd.DataFrame:
    p = REALTIME_DIR / "schedule_archive.csv"
    df = pd.read_csv(p) if p.exists() else pd.DataFrame()
    if not df.empty and "match_id" in df.columns:
        df["match_id"] = df["match_id"].astype(str)
    return df


def read_status(path: Path) -> dict:
    if not path.exists():
        return {"state": "not_started"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "status_error"}


@st.cache_data(ttl=5, show_spinner=False)  # 状态文件很小，5s 就够；实时中控要靠它判断链路是否活着
def load_statuses() -> dict[str, dict]:
    return {
        "monitor": load_monitor_status(),
        "train": read_status(REALTIME_DIR / "train_status.json"),
        "backfill": read_status(REALTIME_DIR / "backfill_status.json"),
    }


@st.cache_data(ttl=10, show_spinner=False)
def latest_data_time() -> str:
    best = None
    for d in [PREDICTION_DIR, RAW_DIR]:
        if not d.exists():
            continue
        for e in os.scandir(d):
            try:
                t = e.stat().st_mtime
            except OSError:
                continue
            if best is None or t > best:
                best = t
    if best is None:
        return "—"
    return datetime.fromtimestamp(best).strftime("%m-%d %H:%M")


@st.cache_data(ttl=600, show_spinner=False)
def load_standings() -> pd.DataFrame:
    teams = load_tables()["teams"]
    if teams.empty:
        return pd.DataFrame()
    return build_proxy_standings(filter_teams_window(teams, mode="all"))


@st.cache_data(ttl=30, show_spinner=False)
def live_battle_options() -> list[dict]:
    rows: set[str] = set()
    if PREDICTION_DIR.exists():
        rows.update(p.stem for p in PREDICTION_DIR.glob("*.csv"))
    b = load_tables()["battles"]
    if b.empty:
        return []
    sub = b[b["battle_id"].isin(rows)].copy()
    if sub.empty:
        return []
    sub["label"] = sub.apply(
        lambda r: f"{r['date']} G{r['game_no']} · {r['team1']} vs {r['team2']}", axis=1)
    return sub.sort_values(["date", "game_no"]).to_dict("records")


@st.cache_data(ttl=15, show_spinner=False)  # 实时页最长 15s 陈旧（原来是 300s）
def live_payload(battle_id: str) -> dict:
    bench = build_winprob_benchmark(battle_id)
    last: dict = {}
    pred = PREDICTION_DIR / f"{battle_id}.csv"
    if pred.exists():
        try:
            df = pd.read_csv(pred)
            if not df.empty:
                last = df.iloc[-1].to_dict()
        except (OSError, pd.errors.ParserError, UnicodeDecodeError):
            last = {}
    snaps: list[dict] = []
    root = resolve_snapshot_root(from_raw=True)
    if root is not None:
        d = root / str(battle_id)
        if d.is_dir():
            snaps = load_battle_jsons(d)
    return {"bench": bench, "last": last, "snaps": snaps,
            "players": load_battle_players(battle_id), "bp": load_battle_bp(battle_id)}


@st.cache_data(ttl=60, show_spinner=False)
def drilldown_payload(battle_id: str) -> dict:
    bench = build_winprob_benchmark(battle_id)
    bp = load_battle_bp(battle_id)
    players = load_battle_players(battle_id)
    lane = build_lane_resource_timeline(battle_id)
    snaps: list[dict] = []
    root = resolve_snapshot_root(from_raw=True)
    if root is not None:
        d = root / str(battle_id)
        if d.is_dir():
            snaps = load_battle_jsons(d)
    return {"bench": bench, "bp": bp, "players": players, "lane": lane, "snaps": snaps}


@st.cache_data(ttl=600, show_spinner=False)
def hero_meta_rows() -> pd.DataFrame:
    meta = aggregate_bp_meta()
    rows = []
    for name, v in (meta.get("heroes") or {}).items():
        rows.append({
            "英雄": str(name),
            "出场": int(v["pick"]["k"]),
            "pick率": float(v["pick"]["rate"]),
            "ban率": float(v["ban"]["rate"]),
            "胜率": float(v["win"]["rate"]),
            "胜场": int(v["win"]["k"]),
            "胜率n": int(v["win"]["n"]),
            "ci_lo": float(v["win"]["ci_low"]),
            "ci_hi": float(v["win"]["ci_high"]),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    try:
        pl = pd.read_csv(PROCESSED_DIR / "players.csv")
        pos = pl.groupby(["hero_name", "position_desc"]).size().unstack(fill_value=0)
        for col in LANES:
            df[col] = df["英雄"].map(pos[col]).fillna(0).astype(int) if col in pos else 0
        df["主位置"] = df[LANES].idxmax(axis=1)
    except (OSError, pd.errors.ParserError):
        df["主位置"] = "—"
    return df


@st.cache_data(ttl=600, show_spinner=False)
def player_stats_table() -> pd.DataFrame:
    pl = pd.read_csv(PROCESSED_DIR / "players.csv")
    if pl.empty:
        return pl
    pl = pl.copy()
    pl["position_desc"] = pl["position_desc"].fillna("未知")
    pl["player_label"] = pl.apply(
        lambda r: f"{r['player_name']} · {r['team_name']}" if pd.notna(r.get("team_name")) else r["player_name"],
        axis=1)
    return pl


def status_light(name: str, state: str, sub: str = "") -> str:
    state = str(state or "")
    if state in ("ready", "done", "live", "day_complete", "clean", "battle_finished", "training"):
        cls, label = "ls-on", {"ready": "READY", "done": "DONE", "live": "LIVE",
                               "day_complete": "DONE", "clean": "OK",
                               "battle_finished": "本局结束", "training": "重训中"}.get(state, "OK")
        light_cls = " ls-live"
    elif state in ("waiting_start", "waiting_battle", "pending", "not_started", "stopped"):
        cls, label = "ls-warn", {"waiting_start": "等待开赛", "waiting_battle": "等待开局",
                                 "pending": "等待中", "stopped": "已停止",
                                 "not_started": "未启动"}.get(state, "WAIT")
        light_cls = " ls-warn"
    elif state in ("error", "status_error", "failed", "api_error", "train_error"):
        cls, label = "ls-err", "异常"
        light_cls = " ls-err"
    else:
        cls, label = "ls-off", state
        light_cls = ""
    sub_html = f'<div class="light-sub">{sub}</div>' if sub else ""
    return (f'<div class="light{light_cls}"><div class="light-name">{name}</div>'
            f'<div class="light-state {cls}">{label}</div>{sub_html}</div>')


def last_live_row(payload: dict) -> dict:
    if payload.get("last"):
        return payload["last"]
    bench = payload.get("bench")
    if bench is not None and not bench.empty:
        r = bench.iloc[-1].to_dict()
        for k in ("kill_diff", "tower_diff", "objective_value_score", "tempo_swing_score", "top_factor"):
            r.setdefault(k, None)
        return r
    return {}


def go_module(code: str, **state: object) -> None:
    st.session_state["module"] = code
    for k in ("drill_match_sel", "drill_battle_sel"):
        st.session_state.pop(k, None)
    for k, v in state.items():
        st.session_state[k] = v
    st.rerun()


# ---------------- 模块：赛事中心 ----------------
def match_row_html(row: pd.Series, wins1: int, wins2: int, cov: int, bo_n: int,
                   snaps: int, status_text: str = "", icon1: str = "", icon2: str = "") -> str:
    st_badge = badge(status_text)
    bo = str(row.get("bo_type") or f"BO{bo_n}")
    dstr = str(row["date"])
    day = dstr[8:10] if len(dstr) >= 10 else "—"
    month = dstr[5:7] if len(dstr) >= 10 else "—"
    cov_cls = "ok" if cov >= bo_n else ""
    winner = None
    if wins1 > wins2:
        winner = row["team1"]
    elif wins2 > wins1:
        winner = row["team2"]
    t1 = str(row["team1"]); t2 = str(row["team2"])
    win1_cls = " style=\"color:var(--blue)\"" if winner == t1 else ""
    win2_cls = " style=\"color:var(--red)\"" if winner == t2 else ""
    cov_note = (f'<span class="meta" style="color:var(--teal);font-weight:700">已采集 {cov}/{bo_n} 局</span>'
                f'<span class="meta">切片 {fmt_int(snaps)}</span>')
    return (
        f'<div class="m-row"><div class="dt">{month}/{day}'
        f'<b>{_esc(row.get("stage") or "—")}</b>{st_badge}</div>'
        f'<div class="tm">{img_tag(icon1, size="sm")}<span{win1_cls}>{_esc(t1)}</span></div>'
        f'<div class="sc">{wins1}:{wins2}<span class="bo">{_esc(bo)}</span></div>'
        f'<div class="tm r"><span{win2_cls}>{_esc(t2)}</span>{img_tag(icon2, size="sm")}</div>'
        f'<div class="act">{cov_note}</div></div>')


def render_schedule(matches: pd.DataFrame, battles: pd.DataFrame, archive: pd.DataFrame) -> None:
    st.markdown(section_head(
        "赛事中心", "赛程 · 采集覆盖 · 复盘入口",
        right=badge("进行中", current_season_label()), kicker="SCHEDULE · 赛程"), unsafe_allow_html=True)
    if matches.empty:
        st.markdown(empty_state(
            "没有赛程数据", "data/analysis/matches.csv 为空或缺失。",
            "python -m kpl_insight.collection.schedule → python -m kpl_insight.datasets.build"),
            unsafe_allow_html=True)
        return
    total_matches = len(matches)
    total_battles = len(battles)
    if not battles.empty and "has_timeline" in battles:
        cov_mask = battles["has_timeline"].astype(bool)
    elif not battles.empty and "snapshot_count" in battles:
        cov_mask = pd.to_numeric(battles["snapshot_count"], errors="coerce").fillna(0) > 0
    else:
        cov_mask = pd.Series(False, index=battles.index)
    cov_battles = int(cov_mask.sum())
    total_snaps = int(pd.to_numeric(battles.get("snapshot_count", 0), errors="coerce").fillna(0).sum())
    stages = int(matches["stage"].nunique()) if "stage" in matches else 0
    rate = cov_battles / total_battles if total_battles else 0.0

    st.markdown(stat_row([
        metric_card("大场", f"{total_matches}", "官方", note=f"覆盖 {stages} 个赛段",
                    src_title="腾讯 KPL 公开赛事接口·赛程", bar="blue"),
        metric_card("已采集对局", f"{cov_battles}/{total_battles}", "官方",
                    note="raw_snapshots / 时间线可复盘", src_title="本地快照目录探测", bar="teal"),
        metric_card("采集覆盖率", f"{rate:.1%}", "官方", note="入表对局中有时间线占比",
                    delta=f"▲ {fmt_int(total_snaps)} 切片", bar="orange"),
        metric_card("数据时钟", latest_data_time(), "官方", note="最近一次本地快照写入",
                    src_title="predictions / raw_snapshots 最新 mtime", bar="purple"),
    ], cols="1.5fr 1fr 1fr 1fr"), unsafe_allow_html=True)

    honors = cached_season_honors()
    if honors.get("state") == "ok":
        st.markdown(panel_html("高光赛季之最（P13）", "自算荣誉",
                               src_title=f"规则 {honors['version']} · 并列全展示 · 稳健排序（Wilson 下界）· 悬停卡片看口径"),
                    unsafe_allow_html=True)
        st.markdown(honor_gallery_html(honors["cards"]), unsafe_allow_html=True)
        with st.expander("复制口径文案（含规则 ID 与样本 n）"):
            st.code("\n\n".join(honors["copy_texts"]), language=None)

    st.markdown(panel_html("按日期覆盖", "官方"), unsafe_allow_html=True)
    st.plotly_chart(coverage_chart(matches, battles), width="stretch")

    st.markdown(panel_html("大场列表", "官方", src_title="状态来自 schedule_archive，覆盖来自本地探测"),
                unsafe_allow_html=True)
    arch_map: dict = {}
    arch_text: dict = {}
    if not archive.empty and "match_id" in archive:
        arch_map = dict(zip(archive["match_id"], archive.get("status", 0)))
        if "status_text" in archive:
            arch_text = dict(zip(archive["match_id"], archive.get("status_text", "")))
    rows = matches.sort_values("date", ascending=False)
    shown = 0
    for _, row in rows.iterrows():
        if shown >= 20:
            st.caption(f"共 {len(rows)} 个大场，仅展示最近 20 个；请用侧栏日期筛选缩小范围。")
            break
        mid = row["match_id"]
        b_sub = battles[battles["match_id"] == mid] if not battles.empty else battles
        # 优先取 processed/battles 的对阵图标
        icon1, icon2 = team_icon(row["team1"]), team_icon(row["team2"])
        bo_n = int(row.get("scheduled_battles") or 0) or max(len(b_sub), 1)
        wins1 = int((b_sub["winner"] == row["team1"]).sum()) if not b_sub.empty else 0
        wins2 = int((b_sub["winner"] == row["team2"]).sum()) if not b_sub.empty else 0
        if not b_sub.empty and "has_timeline" in b_sub:
            cov_n = int(b_sub["has_timeline"].astype(bool).sum())
        elif not b_sub.empty and "snapshot_count" in b_sub:
            cov_n = int((pd.to_numeric(b_sub["snapshot_count"], errors="coerce").fillna(0) > 0).sum())
        else:
            cov_n = 0
        snaps = int(pd.to_numeric(b_sub.get("snapshot_count", 0), errors="coerce").fillna(0).sum()) if not b_sub.empty else 0
        status_num = arch_map.get(mid, 0)
        status_txt = str(arch_text.get(mid) or {0: "未开始", 1: "进行中", 2: "已结束"}.get(int(status_num), "未知"))
        c1, c2 = st.columns([8.4, 1.6])
        with c1:
            st.markdown(match_row_html(row, wins1, wins2, cov_n, bo_n, snaps, status_txt, icon1, icon2),
                        unsafe_allow_html=True)
        with c2:
            if st.button("复盘", key=f"ov_{mid}", width="stretch"):
                go_module("replay", drill_match=mid)
        shown += 1


# ---------------- 模块：实时中控 ----------------
# 监控状态展示：canonical 状态（见 kpl_official_core.MONITOR_STATE_*）→ 徽标 + 说明
MONITOR_STRIP_VIEW = {
    "live": ("live", "采集中"),
    "waiting_start": ("waiting_start", "等待开赛"),
    "waiting_battle": ("waiting_start", "已开赛，等待 BP / 首帧"),
    "battle_finished": ("ready", "本局已结束，等待下一局"),
    "training": ("ready", "今日比赛已结束，后台重训中（采集不中断）"),
    "day_complete": ("day_complete", "当日赛程已结束"),
    "stopped": ("stale", "监控已停止"),
    "error": ("error", "采集 / 接口异常"),
    "not_started": ("stale", "监控脚本尚未运行"),
}


def monitor_freshness_sec(mon: dict) -> float | None:
    """monitor_status.json 的 updated_at 距今多少秒（用于识别“写着 live 但其实卡住了”）。"""
    stamp = str((mon or {}).get("updated_at") or "")
    if not stamp:
        return None
    try:
        return max(0.0, (datetime.now() - datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")).total_seconds())
    except (TypeError, ValueError):
        return None


def monitor_strip(mon: dict) -> str:
    mon = mon or {}
    state = str(mon.get("state") or "not_started")
    tone, default_label = MONITOR_STRIP_VIEW.get(state, ("stale", state))
    parts = [badge(tone, default_label)]
    if mon.get("match"):
        parts.append(f'<span class="mono">{_esc(mon.get("match"))}</span>')
    meta = []
    raw = str(mon.get("state_raw") or "")
    if raw and raw != state:
        meta.append(f"原始状态 {raw}")
    if mon.get("minute") not in (None, ""):
        try:
            meta.append(f"第 {float(mon['minute']):.0f} 分钟")
        except (TypeError, ValueError):
            pass
    if mon.get("camp1_win_prob") not in (None, ""):
        try:
            meta.append(f"camp1 胜率 {float(mon['camp1_win_prob']) * 100:.0f}%")
        except (TypeError, ValueError):
            pass
    lag = mon.get("lag_sec")
    if lag not in (None, ""):
        try:
            meta.append(f"延迟 {float(lag):+.0f}s")
        except (TypeError, ValueError):
            pass
    age = monitor_freshness_sec(mon)
    if age is not None:
        meta.append(f"{age:.0f}s 前更新")
    body = " ".join(parts)
    if meta:
        body += ' <span class="note-line">' + " · ".join(meta) + "</span>"
    msg = str(mon.get("message") or "").strip()
    if msg:
        body += f'<div class="note-line">{_esc(msg)}</div>'
    # 状态写着采集中、但状态文件长时间没更新 → 明确提示可能卡住，而不是静默展示旧数据
    # 阈值 90s：采集间隔会随局势自适应（金差大时拉长），太紧会误报
    if state == "live" and age is not None and age > 90:
        body += (f'<div class="note-line" style="color:#C22">状态文件已 {age:.0f}s 未更新，'
                 f'采集可能中断，请检查监控进程。</div>')
    return panel_html("监控状态", body=body)


def render_live() -> None:
    """实时中控入口：内容放进 fragment 内定时自刷新，避免实时数据被 Streamlit 缓存冻住。"""
    _live_module()


@st.fragment(run_every="8s")
def _live_module() -> None:
    st.markdown(section_head(
        "实时中控", "胜率主图 · 点击曲线任意时刻下钻 · 金差护栏",
        right=badge("估算", "胜率=估算"), kicker="LIVE · 实时"), unsafe_allow_html=True)
    statuses = load_statuses()
    mon = statuses.get("monitor") or {}
    strip = monitor_strip(mon)
    st.markdown(strip, unsafe_allow_html=True)
    if not mon.get("is_live"):
        st.caption("当前无实时采集，下方为本地预测回放（历史对局），非实时数据。")

    options = live_battle_options()
    if not options:
        st.markdown(empty_state(
            "暂无预测时间线",
            "data/realtime/predictions 为空，或 analysis/battles 缺少对应对局。",
            "python -m kpl_insight.collection.monitor --interval 3"),
            unsafe_allow_html=True)
        return
    labels = [o["label"] for o in options]
    default_idx = len(labels) - 1
    if "live_sel" in st.session_state and st.session_state["live_sel"] in labels:
        default_idx = labels.index(st.session_state["live_sel"])
    sel = st.selectbox("对局（本地预测回放）", labels, index=default_idx, key="live_sel", width="stretch")
    rec = options[labels.index(sel)]
    bid = str(rec["battle_id"])
    payload = live_payload(bid)
    bench = payload["bench"]
    if bench is None or bench.empty:
        msg = bench.attrs.get("message", "暂无预测时间线") if bench is not None else "数据加载失败"
        st.markdown(empty_state("无法生成胜率曲线", msg,
                                "检查 predictions CSV 与 raw_snapshots / 模型文件"),
                    unsafe_allow_html=True)
        return

    c1 = str(bench.attrs.get("camp1_team") or rec.get("team1") or "蓝方")
    c2 = str(bench.attrs.get("camp2_team") or rec.get("team2") or "红方")
    wc = int(bench.attrs.get("win_camp") or 0)
    winner = c1 if wc == 1 else (c2 if wc == 2 else None)
    p_now = float(bench["p_v11"].iloc[-1])
    gd_now = float(pd.to_numeric(bench["gold_diff"], errors="coerce").fillna(0).iloc[-1])
    game_no = int(rec.get("game_no") or 0)
    cmp_html = matchup_compare_html(
        c1, c2, p1=p_now, icon1=team_icon(c1), icon2=team_icon(c2),
        sub=f"第 {game_no} 局 · 终局经济差 {fmt_signed(gd_now)}")
    st.markdown(panel_html(
        f"对阵 · {_esc(rec.get('date') or '')}",
        "官方" if wc else "live", body=cmp_html),
        unsafe_allow_html=True)

    lr = last_live_row(payload)
    low_conf = int(pd.to_numeric(bench.get("low_confidence", 0), errors="coerce").fillna(0).sum())
    st.markdown(stat_strip([
        ("蓝方胜率", f"{p_now:.1%}", "V11 模型 · 已校准"),
        ("经济差", fmt_signed(lr.get("gold_diff"), 0),
         ("▲" if gd_now >= 0 else "▼") + f" {fmt_signed(gd_now)}"),
        ("击杀差", fmt_signed(lr.get("kill_diff"), 0), "快照字段"),
        ("推塔差", fmt_signed(lr.get("tower_diff"), 0), "快照字段"),
    ], cols="1.35fr 1fr 1fr 1fr"), unsafe_allow_html=True)
    st.markdown(stat_strip([
        ("资源价值分", fmt_num(lr.get("objective_value_score"), 0), "龙/塔资源加权"),
        ("节奏动量分", fmt_num(lr.get("tempo_swing_score"), 1), "优势是否扩大"),
        ("低置信切片", f"{low_conf}", "解说请谨慎引用绝对值"),
    ], cols="1fr 1fr 1fr"), unsafe_allow_html=True)

    bench_wp = bench_with_prob(bench)
    events = detect_events(payload["snaps"]) if payload["snaps"] else []
    turns = detect_turning_points(bench_wp, events) if not bench_wp.empty else []
    left, right = st.columns([2, 1])
    with left:
        st.markdown(panel_html("胜率主图", "估算", src_title="点击曲线任意点查看该时刻详情"),
                    unsafe_allow_html=True)
        st.plotly_chart(winrate_chart(bench, events=events, turns=turns, teams=(c1, c2)),
                        width="stretch", key="winrate_sel", on_select="rerun",
                        selection_mode="points")
        st.markdown(panel_html("经济差", "官方"), unsafe_allow_html=True)
        st.plotly_chart(economy_chart(bench), width="stretch")
    with right:
        pts = selected_points("winrate_sel")
        if pts:
            minute = float(pts[0]["x"])
            row = bench.iloc[(bench["minute"].astype(float) - minute).abs().idxmin()]
            near = [e for e in events if abs(float(e.get("minute", 0) or 0) - minute) <= 1.5]
            body = (
                f'<div style="font-family:var(--mono);font-size:26px;font-weight:700;color:var(--blue)">'
                f'{float(row["p_v11"]):.1%}</div>'
                f'<div class="note-line">时刻 {float(row["minute"]):.1f}′ · 蓝方胜率</div>'
                f'<div class="note-line">经济差 {fmt_signed(row["gold_diff"], 0)} · '
                f'护栏 {"生效" if row.get("gold_guard_applied") else "未触发"}</div>'
                + (f'<div class="note-line">附近事件：{"；".join(e["label"] for e in near)}</div>'
                   if near else ""))
            st.markdown(panel_html("所选时刻", "估算", body=body), unsafe_allow_html=True)
        st.markdown(panel_html("分阶段偏差（估算）"), unsafe_allow_html=True)
        phases = summarize_winprob_benchmark_phases(bench, win_camp=wc)
        if phases.empty:
            st.markdown(empty_state("无分阶段数据", "时间线切片不足。"), unsafe_allow_html=True)
        else:
            show = phases.copy()
            for col in ["mae_vs_prior", "conflict_rate", "brier_vs_label"]:
                if col in show:
                    show[col] = show[col].map(lambda v: f"{float(v):.3f}" if pd.notna(v) else "—")
            data_table(show)
        approx = bench.attrs.get("gold_ratio_approx", False)
        guard_n = int(bench["gold_guard_applied"].astype(bool).sum())
        st.caption(f"金差先验{'使用近似比例' if approx else '来自真实快照'} · "
                   f"护栏触发 {guard_n} 次 · 冲突阈值 {bench.attrs.get('conflict_threshold', '—')}")

    players = payload.get("players") or {}
    plist = players.get("players") or []
    if plist:
        st.markdown(panel_html("选手速览", "官方", src_title="battle_player_list · 按 MVP 分排序"),
                    unsafe_allow_html=True)
        rows = sorted(plist, key=lambda p: float(p.get("mvp_score") or 0), reverse=True)[:10]
        pt_rows = []
        for p in rows:
            hero = str(p.get("hero_name") or "—")
            mvp = '<span class="bdg b-live">MVP</span>' if p.get("is_mvp") else (
                '<span class="bdg b-done">败方MVP</span>' if p.get("is_lose_mvp") else "")
            pt_rows.append([
                lead_cell(p.get("hero_icon"), str(p.get("player_name") or "—"),
                          str(p.get("position_name") or ""), size="xs", round_=True),
                f'<span class="strong">{_esc(hero)}</span>',
                p.get("kda_text") or "—",
                f"{float(p.get('participation_rate') or 0):.0f}%",
                f"{float(p.get('mvp_score') or 0):.1f}",
                mvp,
            ])
        st.markdown(pt_table(["选手", "英雄", "KDA", "参团", "MVP分", ""], pt_rows,
                             num_cols={3, 4}), unsafe_allow_html=True)
    bp = payload.get("bp") or {}
    if bp.get("steps"):
        st.markdown(panel_html("本局英雄选择", "官方", src_title="bp_list · 双方 Pick"),
                    unsafe_allow_html=True)
        picks = [s for s in bp["steps"] if s.get("action") == "pick"]
        blue = [s for s in picks if s.get("camp") == 1][:5]
        red = [s for s in picks if s.get("camp") == 2][:5]
        def pick_cells(items: list[dict]) -> str:
            if not items:
                return "—"
            return "".join(
                f'<span class="lead" style="margin:2px 10px 2px 0">'
                f'{img_tag(s.get("hero_icon"), size="xs", round_=True)}'
                f'<span class="nm" style="font-size:11.5px">{_esc(s.get("hero_name") or "")}</span></span>'
                for s in items)
        st.markdown(
            f'<div class="panel" style="padding:10px 16px">'
            f'<div style="font-family:var(--mono);font-size:10px;color:var(--blue);'
            f'letter-spacing:1px;margin-bottom:4px">BLUE — {_esc(c1)}</div>{pick_cells(blue)}'
            f'<div style="font-family:var(--mono);font-size:10px;color:var(--red);'
            f'letter-spacing:1px;margin:8px 0 4px">RED — {_esc(c2)}</div>{pick_cells(red)}'
            f'</div>', unsafe_allow_html=True)

    st.markdown(panel_html("与金差先验对标（P07）", "估算",
                           src_title="p_v11=模型，p_gold=金差启发式先验"), unsafe_allow_html=True)
    st.plotly_chart(benchmark_chart(bench), width="stretch")

    st.markdown(panel_html("自动战报", "估算", src_title="generate_battle_report"), unsafe_allow_html=True)
    report = generate_battle_report({"team1": c1, "team2": c2, "winner": winner, "win_camp": wc},
                                    bench_wp, events, turns)
    st.markdown(f'<div class="panel panel-sunken"><div style="font-size:13px;line-height:2;'
                f'color:var(--ink2);white-space:pre-wrap">{_esc(report)}</div></div>',
                unsafe_allow_html=True)
    if turns:
        st.markdown(panel_html("关键拐点", "估算", src_title="detect_turning_points"), unsafe_allow_html=True)
        turn_rows = [{
            "分钟": f"{t['minute']:.0f}′",
            "胜率摆动": f"{t['prob_before']:.0%} → {t['prob_after']:.0%}",
            "幅度": f"{t['delta']:+.0%}",
            "方向": "蓝方" if t["direction"] == "camp1" else "红方",
            "关联事件": "；".join(t.get("events") or ["—"]),
        } for t in turns[:8]]
        data_table(pd.DataFrame(turn_rows))



# ---------------- 模块：单局复盘 ----------------
def render_bp_grid(bp: dict) -> str:
    steps = bp.get("steps") or []
    if not steps:
        return empty_state("暂无 BP 数据", "该对局没有可解析的 bp_list 快照。")
    phases: list[str] = []
    for s in steps:
        ph = s.get("phase") or ""
        if ph and ph not in phases:
            phases.append(ph)

    def cell(acts: list[dict]) -> str:
        if not acts:
            return "<td></td>"
        inner = "".join(
            f'<span class="bp-hero bp-{"pick" if a.get("action") == "pick" else "ban"}">'
            f'{img_tag(a.get("hero_icon"), size="xs", round_=True)}'
            f'{_esc(a.get("hero_name") or "")}</span>'
            for a in acts)
        return f"<td>{inner}</td>"

    rows = "".join(
        f'<tr><td class="bp-phase">{_esc(ph)}</td>'
        f'{cell([s for s in steps if s.get("phase") == ph and s.get("camp") == 1])}'
        f'{cell([s for s in steps if s.get("phase") == ph and s.get("camp") == 2])}</tr>'
        for ph in phases)
    head = ('<tr><td class="bp-phase"></td>'
            '<td><span style="color:var(--blue);font-weight:700">蓝方</span></td>'
            '<td><span style="color:var(--red);font-weight:700">红方</span></td></tr>')
    return f'<table class="bp-grid">{head}{rows}</table>'


def render_roster(bp: dict) -> str:
    picks = [s for s in bp.get("steps") or [] if s.get("action") == "pick"]
    if not picks:
        return empty_state("暂无阵容", "BP 快照不完整。")
    out = []
    for camp, label in ((1, "蓝方阵容"), (2, "红方阵容")):
        by_pos = {s.get("position_name"): s for s in picks if s.get("camp") == camp}
        cells = []
        for pos in LANES:
            s = by_pos.get(pos)
            if s is None:
                cells.append(f'<div class="roster-cell"><div class="roster-pos">{pos}</div>'
                             f'<div class="roster-hero">—</div></div>')
            else:
                cells.append(
                    f'<div class="roster-cell">{img_tag(s.get("hero_icon"), size="sm", round_=True)}'
                    f'<div class="roster-pos">{pos}</div>'
                    f'<div class="roster-hero">{_esc(s.get("hero_name") or "")}</div></div>')
        out.append(f'<div class="panel"><div class="panel-title">{label}</div>'
                   f'<div class="roster">{"".join(cells)}</div></div>')
    return "".join(out)


def bp_meta_table(bp: dict) -> pd.DataFrame:
    try:
        meta = aggregate_bp_meta()
    except Exception:
        return pd.DataFrame()
    rows = hero_meta_rows_for_battle(bp, meta)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = pd.DataFrame()
    out["英雄"] = df.get("英雄", "—")
    out["本局"] = df.get("本局动作", "") + " · " + df.get("本局阵营", "")
    out["ban率"] = df.get("ban率", 0).map(lambda v: f"{float(v):.1%}" if pd.notna(v) else "—")
    out["pick率"] = df.get("pick率", 0).map(lambda v: f"{float(v):.1%}" if pd.notna(v) else "—")
    out["胜率"] = df.get("胜率", 0).map(lambda v: f"{float(v):.1%}" if pd.notna(v) else "—")
    out["样本"] = df.get("胜率_n", 0).map(lambda v: f"n={int(v)}" if pd.notna(v) else "—")
    return out


def player_card_html(p: dict) -> str:
    camp = int(p.get("camp") or 0)
    border = BLUE if camp == 1 else RED
    mvp = ""
    if p.get("is_mvp"):
        mvp = ' <span class="mvp">MVP</span>'
    elif p.get("is_lose_mvp"):
        mvp = ' <span class="mvp lose">败方MVP</span>'
    name = _esc(p.get("player_name") or "—")
    hero = _esc(p.get("hero_name") or "—")
    pos = _esc(p.get("position_name") or "")
    kda = p.get("kda_text") or f"{p.get('kill_num', 0)}/{p.get('death_num', 0)}/{p.get('assist_num', 0)}"
    gold = fmt_int(p.get("gold"))
    part = f"{float(p.get('participation_rate') or 0):.0f}%"
    return (
        f'<div class="pcard" style="border-left:4px solid {border}">'
        f'<div class="pcard-top">{name}{mvp}<span class="pcard-pos">{pos}</span></div>'
        f'<div class="pcard-hero">{hero}</div>'
        f'<div class="pcard-meta"><span>KDA {kda}</span><span>经济 {gold}</span><span>参团 {part}</span></div>'
        f'</div>')


_HONOR_CSS = """
.hg-wrap{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.hg-card{background:var(--card,#FFFFFF);border:1px solid var(--line,#E3E8EE);border-top:3px solid var(--blue,#005691);
         border-radius:6px;padding:9px 12px 10px;display:flex;flex-direction:column;gap:3px;min-height:96px}
.hg-rule{font-size:10px;color:var(--muted,#8A94A6);letter-spacing:.3px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.hg-src{color:#1F2937;background:#F1F3F5;border:1px solid #B8C2CC;border-radius:3px;padding:0 4px;font-size:9px}
.hg-tie{color:#E67E00;font-size:10px}
.hg-title{font-size:12px;color:var(--ink2,#5D6D7E)}
.hg-name{font-size:14px;font-weight:700;color:var(--ink,#1F2937);line-height:1.3}
.hg-value{font-size:17px;color:var(--blue,#005691);line-height:1.1}
.hg-n{font-size:11px;color:var(--muted,#8A94A6);font-weight:400}
.hg-detail{font-size:10.5px;color:var(--muted,#8A94A6);margin-top:auto}
"""


def honor_gallery_html(cards: list[dict]) -> str:
    cells = []
    for c in cards:
        names = "、".join(_esc(e["name"]) for e in c["entries"])
        first = c["entries"][0] if c["entries"] else {"value_text": "—", "n": 0, "detail": ""}
        tie = '<span class="hg-tie">并列</span>' if c["tie"] else ""
        rule_tip = html.escape(str(c.get("rule_summary") or ""))
        cells.append(
            f'<div class="hg-card" title="{rule_tip}">'
            f'<div class="hg-rule"><span class="mono">{_esc(c["rule_id"])}</span>'
            f'<span class="hg-src">{_esc(c["source_tag"])}</span>{tie}</div>'
            f'<div class="hg-title">{_esc(c["title"])}</div>'
            f'<div class="hg-name">{names}</div>'
            f'<div class="hg-value mono">{_esc(first["value_text"])} <span class="hg-n">n={first["n"]}</span></div>'
            f'<div class="hg-detail">{_esc(first["detail"])}</div>'
            f'</div>'
        )
    return f"<style>{_HONOR_CSS}</style><div class='hg-wrap'>" + "".join(cells) + "</div>"


_ATTR_CSS = """
.at-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.at-card{background:var(--card,#FFFFFF);border:1px solid var(--line,#E3E8EE);border-left:3px solid var(--teal,#20B2AA);
         border-radius:6px;padding:10px 12px;display:flex;flex-direction:column;gap:4px}
.at-head{display:flex;align-items:baseline;gap:8px}
.at-v{font-size:18px;color:var(--teal,#20B2AA);font-weight:700}
.at-t{font-size:12px;color:var(--ink2,#5D6D7E)}
.at-h{font-size:13px;color:var(--ink,#1F2937);font-weight:600;line-height:1.35}
.at-n{font-size:11px;color:var(--muted,#8A94A6)}
"""


@st.cache_data(ttl=600, show_spinner=False)
def cached_hero_options() -> list[str]:
    meta = aggregate_bp_meta()
    heroes = meta.get("heroes") or {}
    return sorted(
        heroes.keys(),
        key=lambda h: -int(((heroes[h].get("pick") or {}).get("k")) or 0),
    )


@st.cache_data(ttl=600, show_spinner=False)
def cached_simulate_series(team_a: str, team_b: str, lineup_a: tuple, lineup_b: tuple, best_of: int) -> dict:
    return simulate_series(team_a, team_b, list(lineup_a), list(lineup_b), best_of)


@st.cache_data(ttl=600, show_spinner=False)
def cached_phase_attribution(battle_id: str) -> dict:
    return build_phase_attribution(battle_id)


@st.cache_data(ttl=600, show_spinner=False)
def cached_hero_pool(name: str, kind: str) -> dict:
    return build_hero_pool(name, kind)


@st.cache_data(ttl=600, show_spinner=False)
def cached_hero_matchups(position: str) -> dict:
    return build_hero_matchups(position)


@st.cache_data(ttl=600, show_spinner=False)
def cached_season_honors() -> dict:
    return build_season_honors()


@st.cache_data(ttl=600, show_spinner=False)
def cached_postmatch_brief(match_id: str) -> dict:
    return build_postmatch_brief(match_id)


def render_replay(matches: pd.DataFrame, battles: pd.DataFrame) -> None:
    st.markdown(section_head(
        "单局复盘", "大场 → 对局两级下钻 · BP / 胜率 / 分路 / 选手 / 事件",
        right=badge("已结束"), kicker="REPLAY · 复盘"), unsafe_allow_html=True)
    if matches.empty or battles.empty:
        st.markdown(empty_state("没有可下钻的数据", "analysis/matches 或 battles 为空。",
                                "python -m kpl_insight.datasets.build"), unsafe_allow_html=True)
        return
    m_rows = matches.sort_values("date", ascending=False)
    m_labels = [f"{r.date} · {r.team1} vs {r.team2} · {r.get('bo_type') or ''}" for _, r in m_rows.iterrows()]
    m_map = dict(zip(m_labels, m_rows["match_id"]))
    battle_match_ids: set[str] = set(battles["match_id"]) if not battles.empty else set()
    if not battles.empty and "has_timeline" in battles.columns:
        tl_match_ids: set[str] = set(battles.loc[battles["has_timeline"].astype(bool), "match_id"])
    else:
        tl_match_ids = set()
    order = list(m_map.values())

    def_idx = None
    if "drill_match" in st.session_state and st.session_state["drill_match"] in order:
        cand_idx = order.index(st.session_state["drill_match"])
        if order[cand_idx] in battle_match_ids:
            def_idx = cand_idx
    if def_idx is None:  # 默认优先「有时间线可复盘」的大场
        def_idx = next((i for i, mid_ in enumerate(order) if mid_ in tl_match_ids), None)
    if def_idx is None:
        def_idx = next((i for i, mid_ in enumerate(order) if mid_ in battle_match_ids), 0)
    m_sel = st.selectbox("大场", m_labels, index=def_idx, key="drill_match_sel", width="stretch")
    mid = m_map[m_sel]
    st.session_state["drill_match"] = mid
    b_sub = battles[battles["match_id"] == mid].sort_values("game_no")
    if b_sub.empty:
        st.markdown(empty_state("该大场无对局", "battles 表缺少对应记录。"), unsafe_allow_html=True)
        return
    b_labels = [f"第 {r.game_no} 局 · {r.team1} vs {r.team2} · {fmt_min(r.get('duration_min'))}"
                for _, r in b_sub.iterrows()]
    # 默认选可复盘性最好的对局：有时间线优先 → 快照切片多 → 局序靠后
    rank = b_sub.copy()
    rank["_tl"] = rank["has_timeline"].astype(bool) if "has_timeline" in rank.columns else False
    rank["_snap"] = pd.to_numeric(rank.get("snapshot_count", 0), errors="coerce").fillna(0)
    rank = rank.sort_values(["_tl", "_snap", "game_no"], ascending=[False, False, False])
    best_bid = str(rank.iloc[0]["battle_id"])
    def_b = next((i for i, (_, r) in enumerate(b_sub.iterrows()) if str(r["battle_id"]) == best_bid), len(b_labels) - 1)
    b_sel = st.selectbox("对局", b_labels, index=def_b, key="drill_battle_sel", width="stretch")
    rec = b_sub.iloc[b_labels.index(b_sel)]
    bid = str(rec["battle_id"])
    payload = drilldown_payload(bid)
    bench = payload["bench"]
    c1, c2 = str(rec["team1"]), str(rec["team2"])
    winner = str(rec.get("winner") or "")
    win_camp = 1 if (winner and winner == c1) else (2 if (winner and winner == c2) else 0)
    wins1 = int((b_sub["winner"] == c1).sum())
    wins2 = int((b_sub["winner"] == c2).sum())
    p_last = float(bench["p_v11"].iloc[-1]) if bench is not None and not bench.empty else None
    cmp_block = matchup_compare_html(
        c1, c2, p1=p_last, score1=wins1, score2=wins2,
        icon1=team_icon(c1), icon2=team_icon(c2), sub="大场比分")
    head_body = (
        f'<div style="margin-bottom:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">'
        f'<span class="mono" style="font-size:12px;color:var(--muted)">{_esc(rec["date"])} · '
        f'第 {rec.get("game_no")} 局 · 时长 {fmt_min(rec.get("duration_min"))}</span>{badge("已结束")}'
        f'{"<span class=\"bdg b-clean\">CLEAN</span>" if rec.get("has_timeline") else ""}'
        f'</div>{cmp_block}'
    )
    st.markdown(panel_html("对局", body=head_body), unsafe_allow_html=True)

    brief = cached_postmatch_brief(str(rec["match_id"]))
    if brief.get("state") == "ok":
        b_dl, b_save, b_note = st.columns([1.5, 1.3, 4.2])
        with b_dl:
            st.download_button(
                "下载教练简报（MD）",
                data=brief["markdown"].encode("utf-8"),
                file_name=f"brief_{rec['match_id']}_{brief['meta']['generated_at'][:10]}.md",
                mime="text/markdown",
                width="stretch",
                key=f"brief_dl_{rec['match_id']}",
            )
        with b_save:
            if st.button("存档到 data/reports/", key=f"brief_save_{rec['match_id']}", width="stretch"):
                out_dir = PROJECT_ROOT / "data" / "reports" / str(rec["match_id"])
                out_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                (out_dir / f"brief_postmatch_{ts}.md").write_text(brief["markdown"], encoding="utf-8")
                (out_dir / f"brief_postmatch_{ts}.meta.json").write_text(
                    json.dumps(brief["meta"], ensure_ascii=False, indent=2), encoding="utf-8")
                st.success(f"已存档 {out_dir.name}/brief_postmatch_{ts}.md")
        with b_note:
            st.caption("P18 · 规则版简报：含模型版本 / 生成时间 / 来源标签；舆情章节待 P15 接入")

    tab_all, tab_bp, tab_p07, tab_lane, tab_players, tab_ev = st.tabs(
        ["总览", "BP 看板", "胜率与金差", "经济与资源", "选手面板", "事件归因"])
    bench_wp = bench_with_prob(bench)
    events_list = detect_events(payload["snaps"]) if payload["snaps"] else []
    turns = detect_turning_points(bench_wp, events_list) if bench_wp is not None and not bench_wp.empty else []

    with tab_all:
        st.markdown(stat_row([
            metric_card("快照切片", fmt_int(rec.get("snapshot_count")), "官方", bar="blue"),
            metric_card("经济差", fmt_signed(rec.get("gold_diff"), 0), "官方", bar="teal"),
            metric_card("击杀差", fmt_signed(rec.get("kill_diff"), 0), "官方", bar="red"),
            metric_card("推塔差", fmt_signed(rec.get("tower_diff"), 0), "官方", bar="orange"),
            metric_card("资源差", fmt_signed(rec.get("objective_diff"), 0), "官方", bar="purple"),
        ], cols="1.5fr 1fr 1fr 1fr 1fr"), unsafe_allow_html=True)
        if bench is not None and not bench.empty:
            st.markdown(panel_html("胜率主图", "估算"), unsafe_allow_html=True)
            st.plotly_chart(winrate_chart(bench, events=events_list, turns=turns, teams=(c1, c2)),
                            width="stretch")
        report = generate_battle_report({"team1": c1, "team2": c2, "winner": winner, "win_camp": win_camp},
                                        bench_wp, events_list, turns)
        st.markdown(panel_html("自动战报", "估算"), unsafe_allow_html=True)
        st.markdown(f'<div class="panel panel-sunken"><div style="font-size:13px;line-height:2;'
                    f'color:var(--ink2);white-space:pre-wrap">{_esc(report)}</div></div>',
                    unsafe_allow_html=True)

    with tab_bp:
        bp = payload["bp"]
        if not (bp.get("steps") or []):
            st.markdown(empty_state("暂无 BP 数据", "该对局没有可解析的 bp_list。"), unsafe_allow_html=True)
        else:
            left, right = st.columns([1.5, 1])
            with left:
                st.markdown(panel_html("BP 流程", "官方", src_title="bp_list · 蓝/红 分列"),
                            unsafe_allow_html=True)
                st.markdown(render_bp_grid(bp), unsafe_allow_html=True)
            with right:
                st.markdown(render_roster(bp), unsafe_allow_html=True)
            meta_df = bp_meta_table(bp)
            if not meta_df.empty:
                st.markdown(panel_html("英雄全局 Meta（本局英雄）", "估算",
                                       src_title="全量 BP 归档 Wilson CI"), unsafe_allow_html=True)
                data_table(meta_df, height=360)

    with tab_p07:
        if bench is None or bench.empty:
            st.markdown(empty_state("暂无胜率时间线", "该对局缺少预测 CSV 且无法回放。"),
                        unsafe_allow_html=True)
        else:
            left, right = st.columns([1.6, 1])
            with left:
                st.plotly_chart(benchmark_chart(bench), width="stretch")
                guard_n = int(bench["gold_guard_applied"].astype(bool).sum())
                st.caption(f"护栏触发 {guard_n} 次 · 冲突阈值 {bench.attrs.get('conflict_threshold', '—')}")
            with right:
                phases = summarize_winprob_benchmark_phases(bench, win_camp=bench.attrs.get("win_camp"))
                if phases.empty:
                    st.markdown(empty_state("无分阶段数据", "切片不足。"), unsafe_allow_html=True)
                else:
                    show = phases.copy()
                    for col in ["mae_vs_prior", "conflict_rate", "brier_vs_label"]:
                        if col in show:
                            show[col] = show[col].map(lambda v: f"{float(v):.3f}" if pd.notna(v) else "—")
                    data_table(show)

    with tab_lane:
        lane = payload["lane"]
        if lane.get("empty"):
            st.markdown(empty_state("暂无分路资源数据", lane.get("message") or "快照缺少分路字段。"),
                        unsafe_allow_html=True)
        else:
            kpi = lane.get("kpi") or {}
            st.markdown(stat_row([
                metric_card("资源控制率", fmt_num(kpi.get("resource_control_rate"), 1), "代理",
                            src_title="加权资源事件率", bar="teal"),
                metric_card("地图压力指数", fmt_num(kpi.get("map_pressure_index"), 1), "代理",
                            src_title="map_pressure_index", bar="orange"),
                metric_card("推塔转化", fmt_num(kpi.get("obj_tower_convert"), 1), "代理",
                            src_title="资源→塔转化", bar="purple"),
                metric_card("分路压制", fmt_int(kpi.get("lane_crush_count")), "代理",
                            note="压制分路数", bar="blue"),
            ], cols="1fr 1fr 1fr 1fr"), unsafe_allow_html=True)
            st.plotly_chart(lane_chart(lane.get("frames") or []), width="stretch")
            lane_ev = pd.DataFrame(lane.get("events") or [])
            if not lane_ev.empty:
                st.markdown(panel_html("资源事件", "官方"), unsafe_allow_html=True)
                data_table(lane_ev[["minute", "type", "label", "team", "weight"]]
                           .rename(columns={"minute": "分钟", "type": "类型", "label": "事件",
                                            "team": "阵营", "weight": "权重"}))

    with tab_players:
        players = (payload["players"].get("players") or [])
        if not players:
            st.markdown(empty_state("暂无选手面板", "该对局缺少 battle_player_list 快照。"),
                        unsafe_allow_html=True)
        else:
            st.caption("数据源：快照解析（官方字段）；出装/铭文来自 bp 与 symbol 解析。")
            p_rows = []
            for p in players:
                camp_lab = "蓝" if int(p.get("camp") or 0) == 1 else "红"
                mvp = '<span class="bdg b-live">MVP</span>' if p.get("is_mvp") else (
                    '<span class="bdg b-done">败方MVP</span>' if p.get("is_lose_mvp") else "")
                p_rows.append([
                    lead_cell(p.get("hero_icon"), str(p.get("player_name") or "—"),
                              f"{camp_lab} · {_esc(p.get('position_name') or '')}",
                              size="xs", round_=True),
                    f'<span class="strong">{_esc(p.get("hero_name") or "—")}</span>',
                    p.get("kda_text") or
                    f"{p.get('kill_num', 0)}/{p.get('death_num', 0)}/{p.get('assist_num', 0)}",
                    fmt_int(p.get("gold")),
                    f"{float(p.get('participation_rate') or 0):.0f}%",
                    f"{float(p.get('mvp_score') or 0):.1f}",
                    mvp,
                ])
            st.markdown(pt_table(["选手", "英雄", "KDA", "经济", "参团", "MVP分", ""],
                                 p_rows, num_cols={3, 4, 5}), unsafe_allow_html=True)

    with tab_ev:
        if payload["snaps"]:
            swing = classify_battle_swing(payload["snaps"], win_camp)
            st.markdown(stat_row([
                metric_card("翻盘局", "是" if swing.get("comeback") else "否", "代理",
                            tone="acc" if swing.get("comeback") else None,
                            src_title="早期劣势 vs 最终胜者", bar="orange"),
                metric_card("中期摆动", "是" if swing.get("swing") else "否", "代理",
                            tone="warn" if swing.get("swing") else None,
                            src_title="early→mid 金差方向翻转", bar="purple"),
                metric_card("早期金差均值", fmt_signed(swing.get("early_avg_gold_diff"), 0), "官方",
                            bar="blue"),
            ], cols="1fr 1fr 1fr"), unsafe_allow_html=True)
        att = cached_phase_attribution(bid)
        if att.get("state") == "ok" and att.get("phases"):
            st.markdown(panel_html("阶段切片（P12 · 官方字段差分）", "官方",
                                   src_title="≤8′ / 9–15′ / 16′+ 三段期末与段内变化；胜率均值=估算（V11）"),
                        unsafe_allow_html=True)
            ph_rows = []
            for ph in att["phases"]:
                prob_txt = f"{ph['prob_mean']:.0%}" if ph.get("prob_mean") is not None else "—"
                ph_rows.append({
                    "阶段": ph["label"],
                    "经济差(期末)": fmt_signed(ph["end"]["gd"], 0),
                    "金差段内变化": fmt_signed(ph["delta"]["gd"], 0),
                    "击杀差": fmt_signed(ph["end"]["kd"], 0),
                    "推塔差": fmt_signed(ph["end"]["td"], 0),
                    "资源差": fmt_signed(ph["end"]["rd"], 0),
                    "胜率均值": prob_txt,
                })
            data_table(pd.DataFrame(ph_rows), height=185)
            if att.get("cards"):
                st.markdown(panel_html("归因卡（描述性 · 措辞「伴随」· 非因果）", "描述性",
                                       src_title="描述性统计，未做因果识别；禁止改写为因果结论"),
                            unsafe_allow_html=True)
                cards_html = "".join(
                    f'<div class="at-card"><div class="at-head"><span class="at-v mono">{_esc(c["value"])}</span>'
                    f'<span class="at-t">{_esc(c["title"])}</span></div>'
                    f'<div class="at-h">{_esc(c["headline"])}</div>'
                    f'<div class="at-n">{_esc(c["note"])}</div></div>'
                    for c in att["cards"]
                )
                st.markdown(f"<style>{_ATTR_CSS}</style><div class='at-grid'>{cards_html}</div>",
                            unsafe_allow_html=True)
            if att.get("factors"):
                st.markdown(panel_html("叙事因子（非权重 · 禁止按模型权重引用）", "叙事因子",
                                       src_title="FeatureBuilder.explain · 非 SHAP · 仅叙事用途"),
                            unsafe_allow_html=True)
                fac_rows = [{
                    "因子": f["factor"],
                    "指向": f["leader"] or "—",
                    "说明": f["description"],
                } for f in att["factors"]]
                data_table(pd.DataFrame(fac_rows), height=210)
        ev_df = pd.DataFrame(events_list)
        if ev_df.empty:
            st.markdown(empty_state("暂无事件", "快照差分未识别到一血/推塔/龙类事件。"),
                        unsafe_allow_html=True)
        else:
            ev_show = ev_df.rename(columns={
                "minute": "分钟", "type": "类型", "label": "事件", "team": "阵营", "weight": "权重"})
            ev_show["分钟"] = ev_show["分钟"].map(lambda v: f"{float(v):.1f}′")
            ev_show["类型"] = ev_show["类型"].map(lambda v: EVENT_CN.get(str(v), str(v)))
            st.markdown(panel_html("事件时间线", "官方"), unsafe_allow_html=True)
            data_table(ev_show, height=380)
        if turns:
            st.markdown(panel_html("胜率拐点", "估算"), unsafe_allow_html=True)
            turn_rows = [{
                "分钟": f"{t['minute']:.0f}′",
                "胜率摆动": f"{t['prob_before']:.0%} → {t['prob_after']:.0%}",
                "幅度": f"{t['delta']:+.0%}",
                "方向": "蓝方" if t["direction"] == "camp1" else "红方",
                "关联事件": "；".join(t.get("events") or ["—"]),
            } for t in turns[:10]]
            data_table(pd.DataFrame(turn_rows))


# ---------------- 模块：战队画像 ----------------
def render_teams(matches: pd.DataFrame, battles: pd.DataFrame, teams: pd.DataFrame) -> None:
    st.markdown(section_head(
        "战队画像", "积分榜 · 风格雷达 · 对阵记录",
        right=badge("代理", "风格=代理"), kicker="TEAMS · 战队"), unsafe_allow_html=True)
    standings = load_standings()
    if standings.empty or teams.empty:
        st.markdown(empty_state("暂无战队数据", "analysis/teams.csv 为空。",
                                "python -m kpl_insight.datasets.build"), unsafe_allow_html=True)
        return
    st.markdown(stat_strip([
        ("战队数", fmt_int(len(standings)), "官方口径"),
        ("样本对局", fmt_int(standings["games"].sum()), "analysis/teams"),
        ("平均胜率", f"{standings['win_rate'].mean():.1%}", "Wilson CI"),
        ("平均金差", fmt_signed(standings["avg_gold_diff"].mean(), 0), "各队均值 · 蓝方为正"),
    ], cols="1fr 1fr 1fr 1fr"), unsafe_allow_html=True)

    st.markdown(panel_html("积分榜（Wilson CI）", "官方", src_title="build_proxy_standings · 胜率置信区间"),
                unsafe_allow_html=True)
    tm_rows = []
    for _, r in standings.sort_values("rank").iterrows():
        wr = float(r["win_rate"]) * 100
        tm_rows.append([
            f'<span class="strong">{int(r["rank"])}</span>',
            lead_cell(team_icon(r["team"]), r["team"], size="sm"),
            f'{int(r["wins"])}W {int(r["losses"])}L',
            str(int(r["games"])),
            mini_bar(wr, "var(--blue)"),
            f'[{float(r["wilson_lo"]):.1%}, {float(r["wilson_hi"]):.1%}]',
            fmt_signed(r["avg_gold_diff"], 0),
            fmt_signed(r["net_gold"], 0),
            tier_badge(float(r["win_rate"])),
        ])
    st.markdown(pt_table(
        ["排名", "战队", "胜负", "局数", "胜率", "胜率CI", "平均金差", "净胜分", "档位"],
        tm_rows, num_cols={0, 3, 5, 6, 7}), unsafe_allow_html=True)

    team = st.selectbox("查看战队", standings.sort_values("rank")["team"].tolist(),
                        key="team_sel", width="stretch")
    t_sub = teams[teams["team"] == team]
    left, right = st.columns([1, 1.35])
    with left:
        st.markdown(panel_html(f"{team} 风格雷达", "代理", src_title="team_style_radar · 五轴 0–1 归一"),
                    unsafe_allow_html=True)
        st.plotly_chart(radar_chart(team_style_radar(t_sub), team), width="stretch")
    with right:
        t_dec = t_sub[t_sub["win"].notna()] if not t_sub.empty else t_sub
        wins = int((t_dec["win"] == 1).sum()) if not t_dec.empty else 0
        games = len(t_dec)
        undecided = len(t_sub) - games
        w_rate = wins / games if games else 0.0
        st.markdown(stat_strip([
            ("战绩", f"{wins}W {games - wins}L",
             f"{games} 局样本" + (f" · 未结算 {undecided} 场" if undecided else "")),
            ("胜率", f"{w_rate:.1%}", "analysis/teams"),
            ("平均金差", fmt_signed(t_sub["gold_diff"].mean() if games else 0, 0), "蓝方为正"),
        ], cols="1fr 1fr 1.2fr"), unsafe_allow_html=True)
        h2h = t_dec.groupby("opponent").agg(
            胜=("win", lambda s: int((s == 1).sum())),
            局数=("win", "size"),
        ).reset_index()
        h2h["胜率"] = h2h["胜"] / h2h["局数"]
        h2h = h2h.sort_values(["局数", "胜率"], ascending=[False, False]).head(8)
        st.markdown(panel_html("对阵记录 H2H", "官方"), unsafe_allow_html=True)
        h2h_rows = [[
            lead_cell(team_icon(r["opponent"]), r["opponent"], size="xs"),
            f'<span class="strong">{int(r["胜"])}W</span> / {int(r["局数"] - r["胜"])}L',
            str(int(r["局数"])),
            mini_bar(float(r["胜率"]) * 100, "var(--teal)"),
        ] for _, r in h2h.iterrows()]
        st.markdown(pt_table(["对手", "胜负", "局数", "胜率"], h2h_rows, num_cols={2}),
                    unsafe_allow_html=True)

    recent = battles[(battles["team1"] == team) | (battles["team2"] == team)].copy()
    if not recent.empty:
        recent = recent.sort_values(["date", "game_no"], ascending=False).head(10)
        recent["结果"] = recent.apply(
            lambda r: "胜" if r["winner"] == team else ("负" if pd.notna(r["winner"]) else "—"), axis=1)
        st.markdown(panel_html("最近对局", "官方"), unsafe_allow_html=True)
        r_rows = []
        for _, r in recent.iterrows():
            res = str(r["结果"])
            res_html = ('<span class="strong" style="color:var(--teal)">胜</span>' if res == "胜"
                        else '<span class="strong" style="color:var(--red)">负</span>' if res == "负"
                        else "—")
            r_rows.append([
                str(r["date"])[5:],
                f'G{r["game_no"]}',
                lead_cell(team_icon(r["team1"]), r["team1"], size="xs"),
                lead_cell(team_icon(r["team2"]), r["team2"], size="xs"),
                res_html,
                fmt_min(r.get("duration_min")),
                fmt_signed(r.get("gold_diff"), 0),
            ])
        st.markdown(pt_table(["日期", "局", "蓝方", "红方", "结果", "时长", "金差"],
                             r_rows, num_cols={1, 5, 6}), unsafe_allow_html=True)

    pool = cached_hero_pool(team, "team")
    if pool.get("state") == "ok":
        br = pool["breadth"]
        st.markdown(panel_html(f"{team} 英雄池（P11）", "官方",
                               src_title=f"广度：池 {br['pool_size']} · HHI {br['hhi']} · 有效 {br['effective']}"
                                         f"｜生疏 = 过去 ≥{pool['stale_threshold']} 局未用｜胜率=已完赛"),
                    unsafe_allow_html=True)
        pool_rows = []
        for r in pool["rows"][:15]:
            wr_txt = f"{r['wr']:.1%}" if r["wr"] is not None else "—"
            ci_txt = f"[{r['ci_low']:.1%}, {r['ci_high']:.1%}]" if r["ci_low"] is not None else "—"
            pool_rows.append([
                lead_cell(hero_icon(r["hero"]), r["hero"], size="sm", round_=True),
                str(r["games"]),
                wr_txt,
                ci_txt,
                '<span class="bdg b-wait">生疏</span>' if r["stale"] else "",
            ])
        st.markdown(pt_table(["英雄", "出场", "胜率", "胜率CI", "状态"], pool_rows, num_cols={1}),
                    unsafe_allow_html=True)


# ---------------- 模块：选手排行 ----------------
PLAYER_METRICS = {
    "KDA": "kda", "击杀": "kill_num", "助攻": "assist_num",
    "输出占比": "hurt_to_hero_total_rate", "承伤占比": "be_hurt_by_hero_total_rate",
    "参团率": "participation_rate", "MVP分": "mvp_score",
}


def render_players() -> None:
    st.markdown(section_head(
        "选手排行", "位置维度 · 官方统计字段 · 点击进入详情",
        right=badge("官方"), kicker="PLAYERS · 选手"), unsafe_allow_html=True)
    pl = player_stats_table()
    if pl.empty:
        st.markdown(empty_state("暂无选手数据", "data/processed/players.csv 为空。"),
                    unsafe_allow_html=True)
        return
    positions = ["全部"] + [p for p in LANES if p in set(pl["position_desc"])]
    pos = st.selectbox("位置", positions, key="pl_pos", width="stretch")
    metric = st.selectbox("指标", list(PLAYER_METRICS.keys()), index=0, key="pl_metric", width="stretch")
    min_games = st.slider("最少出场", 1, 10, 3, key="pl_min")
    col = PLAYER_METRICS[metric]

    agg = pl.groupby(["player_label", "player_name", "team_name", "position_desc"]).agg(
        games=("battle_id", "size"),
        kda=("kda", "mean"),
        kill_num=("kill_num", "mean"),
        assist_num=("assist_num", "mean"),
        hurt_to_hero_total_rate=("hurt_to_hero_total_rate", "mean"),
        be_hurt_by_hero_total_rate=("be_hurt_by_hero_total_rate", "mean"),
        participation_rate=("participation_rate", "mean"),
        mvp_score=("mvp_score", "mean"),
        mvp_count=("is_mvp", "sum"),
        player_icon=("player_icon", "first"),
        team_icon=("team_icon", "first"),
    ).reset_index()
    if pos != "全部":
        agg = agg[agg["position_desc"] == pos]
    agg = agg[agg["games"] >= min_games].sort_values(col, ascending=False).reset_index(drop=True)
    if agg.empty:
        st.markdown(empty_state("该筛选下没有选手", "请降低最少出场或换位置/指标。"),
                    unsafe_allow_html=True)
        return
    st.caption(f"样本：{len(agg)} 名选手 · 指标「{metric}」均值 · 位置 {pos} · 最少出场 {min_games}")

    rank_colors = {1: "var(--orange)", 2: "var(--blue)", 3: "var(--teal)"}
    p_rows = []
    for i, (_, r) in enumerate(agg.head(60).iterrows(), start=1):
        v = float(r[col])
        if col in ("hurt_to_hero_total_rate", "be_hurt_by_hero_total_rate"):
            metric_cell = mini_bar(v * 100, "var(--purple)")
        elif col == "participation_rate":
            metric_cell = mini_bar(v, "var(--purple)")
        elif col in ("kda", "mvp_score"):
            metric_cell = f'<span class="strong">{v:.1f}</span>'
        else:
            metric_cell = f'<span class="strong">{v:.1f}</span>'
        rank_html = (f'<span class="strong" style="color:{rank_colors.get(i, "var(--ink)")}">{i}</span>'
                     if i <= 3 else f'<span class="strong">{i}</span>')
        p_rows.append([
            rank_html,
            lead_cell(r.get("player_icon"), str(r.get("player_name") or "—"),
                      str(r.get("position_desc") or ""), size="xs", round_=True),
            lead_cell(r.get("team_icon"), str(r.get("team_name") or "—"), size="xs"),
            str(int(r["games"])),
            f'{float(r["kda"]):.1f}',
            str(int(r["mvp_count"])),
            mini_bar(float(r["participation_rate"]), "var(--teal)"),
            metric_cell,
        ])
    st.markdown(panel_html("排行榜", "官方",
                           src_title="players.csv 均值聚合 · 出场 / KDA / MVP / 参团 / 核心指标"),
                unsafe_allow_html=True)
    st.markdown(pt_table(["排名", "选手", "战队", "出场", "KDA", "MVP", "参团", metric],
                         p_rows, num_cols={0, 3, 4, 5}), unsafe_allow_html=True)

    st.markdown(panel_html("选手英雄池（P11）", "官方",
                           src_title="池广度 = 不重复英雄数 / HHI / 有效英雄数 exp(Shannon)；胜率=已完赛"),
                unsafe_allow_html=True)
    pool_labels = agg["player_label"].head(30).tolist()
    name_by_label = dict(zip(agg["player_label"], agg["player_name"]))
    if pool_labels:
        pool_sel = st.selectbox("选手", pool_labels, key="pool_player", width="stretch")
        ppool = cached_hero_pool(str(name_by_label.get(pool_sel, pool_sel)), "player")
        if ppool.get("state") == "ok":
            br = ppool["breadth"]
            st.caption(f"池 {br['pool_size']} · HHI {br['hhi']} · 有效英雄 {br['effective']} · 共 {ppool['total_games']} 局"
                       f"｜生疏 = 过去 ≥{ppool['stale_threshold']} 局未用")
            pp_rows = []
            for r in ppool["rows"][:12]:
                wr_txt = f"{r['wr']:.1%}" if r["wr"] is not None else "—"
                ci_txt = f"[{r['ci_low']:.1%}, {r['ci_high']:.1%}]" if r["ci_low"] is not None else "—"
                pp_rows.append([
                    lead_cell(hero_icon(r["hero"]), r["hero"], size="sm", round_=True),
                    str(r["games"]),
                    wr_txt,
                    ci_txt,
                    '<span class="bdg b-wait">生疏</span>' if r["stale"] else "",
                ])
            st.markdown(pt_table(["英雄", "出场", "胜率", "胜率CI", "状态"], pp_rows, num_cols={1}),
                        unsafe_allow_html=True)
        else:
            st.caption(ppool.get("message") or "暂无数据")


# ---------------- 模块：英雄 Meta ----------------
def render_heroes() -> None:
    st.markdown(section_head(
        "英雄 Meta", "出场率 × 胜率散点 · 组合胜率",
        right=badge("估算", "胜率=估算"), kicker="META · 英雄"), unsafe_allow_html=True)
    df = hero_meta_rows()
    if df.empty:
        st.markdown(empty_state("暂无英雄 Meta", "BP 归档为空，请先回补对局。",
                                "python -m kpl_insight.collection.backfill"), unsafe_allow_html=True)
        return
    pos_sel = st.multiselect("位置（空=全部）", LANES, key="hero_pos", width="stretch")
    min_games = st.slider("最少出场", 1, 30, 5, key="hero_min")
    sub = df[df["出场"] >= min_games].copy()
    if pos_sel:
        mask = sub[LANES[0]].fillna(0).astype(int) > 0
        for p in pos_sel[1:]:
            mask = mask | (sub[p].fillna(0).astype(int) > 0)
        sub = sub[mask]
    sub = sub.sort_values(["出场", "胜率"], ascending=[False, False])
    if sub.empty:
        st.markdown(empty_state("该筛选下没有英雄", "请降低最少出场或放宽位置。"),
                    unsafe_allow_html=True)
        return
    st.caption(f"样本：{len(sub)} 个英雄 · 全部 BP 归档 {int(df['出场'].sum())} 次出场")
    st.markdown(stat_strip([
        ("英雄池", fmt_int(len(sub)), "筛选后"),
        ("最高胜率", f"{sub['胜率'].max():.1%}", str(sub.loc[sub["胜率"].idxmax(), "英雄"])),
        ("最高禁用率", f"{sub['ban率'].max():.1%}", str(sub.loc[sub["ban率"].idxmax(), "英雄"])),
        ("最高出场", fmt_int(sub["出场"].max()), str(sub.loc[sub["出场"].idxmax(), "英雄"])),
    ], cols="1fr 1fr 1fr 1fr"), unsafe_allow_html=True)

    st.markdown(panel_html("英雄散点（Wilson CI 误差线）", "估算",
                           src_title="点大小=出场次数，颜色=主位置"), unsafe_allow_html=True)
    st.plotly_chart(hero_scatter(sub), width="stretch")

    show = sub.head(80)
    h_rows = []
    for i, (_, r) in enumerate(show.iterrows(), start=1):
        h_rows.append([
            f'<span class="strong">{i}</span>',
            lead_cell(hero_icon(r["英雄"]), r["英雄"], size="sm", round_=True),
            str(r.get("主位置") or "—"),
            str(int(r["出场"])),
            mini_bar(float(r["pick率"]) * 100, "var(--teal)"),
            mini_bar(float(r["ban率"]) * 100, "var(--orange)"),
            mini_bar(float(r["胜率"]) * 100, "var(--blue)"),
            f'[{float(r["ci_lo"]):.1%}, {float(r["ci_hi"]):.1%}]',
            tier_badge(float(r["胜率"])),
        ])
    st.markdown(panel_html("英雄梯度榜", "估算",
                           src_title="aggregate_bp_meta · Wilson CI · S/A/B/C 按胜率分档"),
                unsafe_allow_html=True)
    st.markdown(pt_table(["排名", "英雄", "主位置", "出场", "pick率", "ban率", "胜率", "胜率CI", "档位"],
                         h_rows, num_cols={0, 3, 7}), unsafe_allow_html=True)

    try:
        meta = aggregate_bp_meta()
        lineup3 = meta.get("lineup_3") or {}
        combos = [{
            "组合": " + ".join(k),
            "样本": int(v.get("n", 0)),
            "胜场": int(v.get("wins", 0)),
        } for k, v in lineup3.items()]
        cdf = pd.DataFrame(combos)
        if not cdf.empty:
            cdf = cdf[cdf["样本"] >= 3].sort_values(["样本", "胜场"], ascending=[False, False]).head(15)
            cdf["胜率"] = (cdf["胜场"] / cdf["样本"]).map(lambda v: f"{v:.1%}")
            st.markdown(panel_html("三人核心组合（n≥3）", "估算", src_title="lineup_3 组合胜率"),
                        unsafe_allow_html=True)
            data_table(cdf, height=380)
    except Exception:
        pass

    st.markdown(panel_html("同位置对位（P11 · 历史对位关联）", "代理",
                           src_title="同局同位置、不同战队；方向 = 蓝方英雄 vs 红方英雄；n<8 标「不足」，不作机制克制断言"),
                unsafe_allow_html=True)
    mu_pos = st.selectbox("对位位置", LANES, key="mu_pos", width="stretch")
    mu = cached_hero_matchups(mu_pos)
    if mu.get("state") == "ok" and mu.get("rows"):
        mu_rows = []
        for r in mu["rows"][:25]:
            wr_txt = f"{r['wr']:.1%}"
            ci_txt = f"[{r['ci_low']:.1%}, {r['ci_high']:.1%}]"
            tag = '<span class="bdg b-wait">不足</span>' if r["insufficient"] else ""
            mu_rows.append([
                lead_cell(hero_icon(r["hero_blue"]), r["hero_blue"], size="sm", round_=True),
                lead_cell(hero_icon(r["hero_red"]), r["hero_red"], size="sm", round_=True),
                str(r["n"]),
                wr_txt,
                ci_txt,
                tag,
            ])
        st.markdown(pt_table(["蓝方英雄", "红方英雄", "n", "蓝方胜率", "胜率CI", "判定"], mu_rows, num_cols={2, 3}),
                    unsafe_allow_html=True)
    else:
        st.caption("该位置暂无可展示的历史对位（样本不足）。")


# ---------------- 模块：大场模拟 ----------------
def render_sim() -> None:
    st.markdown(section_head(
        "大场模拟", "赛前先验 / 阵容假设 → 单局 p → BO 系列赛（解析 · 独立同分布）",
        right=badge("估算", "模拟=估算"), kicker="SIM · 模拟"), unsafe_allow_html=True)
    standings = load_standings()
    teams = standings.sort_values("rank")["team"].tolist() if not standings.empty else []
    if len(teams) < 2:
        st.markdown(empty_state("暂无战队数据", "analysis/teams.csv 为空。",
                                "python -m kpl_insight.datasets.build"), unsafe_allow_html=True)
        return
    c1, c2, c3 = st.columns([2.2, 2.2, 1.4])
    with c1:
        team_a = st.selectbox("战队 A", teams, index=0, key="sim_a", width="stretch")
    with c2:
        team_b = st.selectbox("战队 B", teams, index=1, key="sim_b", width="stretch")
    with c3:
        bo_label = st.selectbox("赛制", ["BO3", "BO5", "BO7"], index=1, key="sim_bo", width="stretch")
    best_of = {"BO3": 3, "BO5": 5, "BO7": 7}[bo_label]
    if team_a == team_b:
        st.error("战队 A 与 B 不能相同。")
        return

    heroes = cached_hero_options()
    st.markdown(panel_html("阵容假设（可选 · 每边最多 5 个英雄；留空或不足 3 个则仅用战队先验）", "估算",
                           src_title="命中历史三人核心组合与英雄稳健胜率时自动纳入合成"),
                unsafe_allow_html=True)
    la_col, lb_col = st.columns(2)
    with la_col:
        lineup_a = st.multiselect(f"{team_a} 阵容", heroes, max_selections=5, key="sim_lu_a")
    with lb_col:
        lineup_b = st.multiselect(f"{team_b} 阵容", heroes, max_selections=5, key="sim_lu_b")
    dup = set(lineup_a) & set(lineup_b)
    if dup:
        st.error(f"非法 BP：英雄重复 {'、'.join(sorted(dup))}")
        return
    for team, lineup in ((team_a, lineup_a), (team_b, lineup_b)):
        pool = cached_hero_pool(team, "team")
        if pool.get("state") == "ok" and lineup:
            known = {r["hero"] for r in pool["rows"]}
            outside = [h for h in lineup if h not in known]
            if outside:
                st.warning(f"{team} 历史未见出场：{'、'.join(outside)}（仍可模拟，样本权重会相应降低）")

    sim = cached_simulate_series(team_a, team_b, tuple(lineup_a), tuple(lineup_b), best_of)
    if sim.get("state") != "ok":
        st.markdown(empty_state("暂时无法模拟", sim.get("message") or "数据不足"), unsafe_allow_html=True)
        return

    st.markdown(stat_row([
        metric_card("单局 p", f"{sim['p_game']:.1%}", "估算",
                    note=f"CI {sim['p_game_ci'][0]:.1%}~{sim['p_game_ci'][1]:.1%}", bar="blue"),
        metric_card(f"{team_a} 大场胜率", f"{sim['series_p']:.1%}", "估算",
                    note=f"{bo_label} · CI {sim['series_ci'][0]:.1%}~{sim['series_ci'][1]:.1%}",
                    bar="orange", tone="acc"),
        metric_card("等效样本", f"{sim['total_weight']:.0f}", "估算",
                    note="证据加权 · 单项封顶 120", bar="teal"),
        metric_card("模式", sim["mode"], "估算", note="解析计算 · 可复现导出", bar="purple"),
    ], cols="1.4fr 1.5fr 1fr 1fr"), unsafe_allow_html=True)

    left, right = st.columns([1.6, 1])
    with left:
        st.markdown(panel_html("证据分解（logit 加权合成）", "估算",
                               src_title="权重 = 等效样本；结果为历史关联估计，非官方预测"),
                    unsafe_allow_html=True)
        sig_rows = [[
            f'{_esc(s["signal"])} <span style="color:var(--muted);font-size:11px">（{_esc(s["source"])}）</span>',
            f"{s['prob_a']:.1%}",
            str(int(s["n"])),
            f"{s['weight']:.0f}",
            _esc(s["detail"]),
        ] for s in sim["signals"]]
        st.markdown(pt_table([f"信号", f"{team_a} 视角", "n", "权重", "明细"], sig_rows, num_cols={1, 2, 3}),
                    unsafe_allow_html=True)
    with right:
        st.markdown(panel_html("局分分布", "估算", src_title="独立同分布解析；先至 ⌈n/2⌉ 胜"),
                    unsafe_allow_html=True)
        m_wins = (best_of + 1) // 2
        dist_sorted = sorted(sim["score_dist"].items(),
                             key=lambda kv: (-int(kv[0].split("-")[0]), -int(kv[0].split("-")[1])))
        dist_rows = [[
            f"<span class='strong'>{score}</span>",
            f"{v:.1%}",
            mini_bar(v * 100, "var(--blue)" if int(score.split("-")[0]) == m_wins else "var(--orange)"),
        ] for score, v in dist_sorted]
        st.markdown(pt_table(["比分", "概率", ""], dist_rows, num_cols={1}), unsafe_allow_html=True)
        st.caption(f"局分按「{team_a} 先」在前；{team_b} 对称")

    st.caption(" · ".join(sim["notes"]))
    if sim["warnings"]:
        st.warning("；".join(sim["warnings"]))
    st.download_button(
        "导出模拟配置（JSON · 可复现）",
        data=json.dumps(sim, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name=f"sim_{team_a}_vs_{team_b}_{bo_label}.json",
        mime="application/json",
        key="sim_dl",
    )


# ---------------- 模块：数据健康 ----------------
def render_ops() -> None:
    st.markdown(section_head(
        "数据健康", "采集链路 · 模型指标 · 覆盖与缺口",
        right=badge("估算"), kicker="OPS · 运维"), unsafe_allow_html=True)
    statuses = load_statuses()
    mon = statuses.get("monitor") or {}
    train = statuses.get("train") or {}
    backfill = statuses.get("backfill") or {}
    st.markdown('<div class="light-row">' + "".join([
        status_light("监控链路", mon.get("state", "not_started"),
                     f"更新 {_esc(mon.get('updated_at') or '—')}"),
        status_light("历史回补", backfill.get("state", "not_started"),
                     f"{backfill.get('success', 0)}/{backfill.get('target_count', '—')} 成功"),
        status_light("模型训练", train.get("state", "not_started"),
                     _esc(train.get("version") or train.get("model_name") or "—")),
    ]) + '</div>', unsafe_allow_html=True)

    model = load_model()
    artifact_ok = model is not None
    st.markdown(stat_strip([
        ("模型版本", _esc(train.get("version") or "—"), f"artifact {'就绪' if artifact_ok else '缺失'}"),
        ("Holdout Brier(全)", safe_f(train.get("holdout_real_brier"), 4), "clean 真实局 holdout"),
        ("Holdout ECE", safe_f(train.get("holdout_real_ece"), 4), "期望校准误差"),
        ("训练时间", _esc(str(train.get("trained_at") or "—")[:16]), "train_status.json"),
    ], cols="1.2fr 1fr 1fr 1fr"), unsafe_allow_html=True)

    st.markdown(panel_html("分阶段 Holdout", "估算", src_title="train_status.json · clean 真实局"),
                unsafe_allow_html=True)
    phase_df = pd.DataFrame([
        {"阶段": "early (≤8′)", "Brier": train.get("holdout_early_brier")},
        {"阶段": "mid (9–15′)", "Brier": train.get("holdout_mid_brier")},
        {"阶段": "late (16′+)", "Brier": train.get("holdout_late_brier")},
        {"阶段": "全部", "Brier": train.get("holdout_real_brier")},
    ])
    phase_df["Brier"] = phase_df["Brier"].map(lambda v: safe_f(v, 4))
    data_table(phase_df, height=230)
    st.caption("说明：以 clean 真实局分阶段 Brier / ECE 为主指标，不以混合 AUC 误导。")

    cov = historical_coverage_report()
    st.markdown(stat_strip([
        ("归档大场", fmt_int(cov.get("archive_matches")), "官方"),
        ("归档对局", fmt_int(cov.get("archive_battles")), "官方"),
        ("已采快照对局", fmt_int(cov.get("raw_battles")), "本地探测"),
        ("覆盖率", f"{cov.get('coverage_rate', 0):.1%}", "已采 ÷ 归档（全档案）"),
    ], cols="1fr 1fr 1fr 1fr"), unsafe_allow_html=True)
    missing = cov.get("missing_battles") or []
    if missing:
        st.warning(f"{len(missing)} 个对局缺少快照（回补可补齐）。示例：{', '.join(missing[:5])}…")

    st.markdown(panel_html("数据表规模", "官方"), unsafe_allow_html=True)
    sizes = []
    for name in ["matches", "battles", "teams", "events"]:
        p = ANALYSIS_DIR / f"{name}.csv"
        sizes.append({"表": f"analysis/{name}",
                      "行数": fmt_int(sum(1 for _ in open(p, encoding="utf-8")) - 1) if p.exists() else "—"})
    for name in ["schedule", "battles", "bp", "players"]:
        p = PROCESSED_DIR / f"{name}.csv"
        sizes.append({"表": f"processed/{name}",
                      "行数": fmt_int(sum(1 for _ in open(p, encoding="utf-8")) - 1) if p.exists() else "—"})
    data_table(pd.DataFrame(sizes), height=280)

    with st.expander("状态文件明细（JSON）"):
        for name, d in statuses.items():
            st.markdown(f"**{name}**")
            st.json(d)


# ---------------- 壳：顶栏 + 模块轨 + 分发 ----------------
LEAGUE_NAMES = {
    "20260001": "2026 春季赛",
    "20260002": "2026 挑战者杯",
    "20260003": "2026 夏季赛",
    "20260004": "2026 年度总决赛",
}


def current_season_label() -> str:
    """按归档中最近已开赛场次推导当前赛季名（展示随数据同步，避免硬编码过期）。"""
    try:
        a = load_archive()
        if a.empty or "start_time" not in a.columns:
            return "2026 赛季"
        started = a[pd.to_datetime(a["start_time"], errors="coerce") <= pd.Timestamp.now()]
        if started.empty:
            return "2026 赛季"
        lid = str(started.sort_values("start_time")["league_id"].iloc[-1])
        return LEAGUE_NAMES.get(lid, f"{lid[:4]} 赛季")
    except Exception:
        return "2026 赛季"


def topbar_html(model: str) -> str:
    mon = load_statuses().get("monitor") or {}
    live_dot = '<span class="dot-live"></span>' if mon.get("is_live") else ""
    return (
        '<div class="topbar"><div class="brand"><span class="brand-mark"></span><div>'
        '<div class="brand-name">KPL 数据中心</div>'
        '<div class="brand-sub">KING PRO LEAGUE · DATA CONSTRUCTIVISM</div></div></div>'
        '<div class="topmeta">'
        f'<span class="chip">{live_dot}{_esc(current_season_label())}</span>'
        f'<span class="chip">模型 <b>{_esc(model)}</b></span>'
        f'<span class="chip mono">数据时钟 {latest_data_time()}</span>'
        '</div></div>'
    )


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            '<div class="side-brand"><span class="brand-mark"></span><span>KPL 数据中心</span></div>',
            unsafe_allow_html=True)
        st.markdown('<div class="nav-group">模块</div>', unsafe_allow_html=True)
        st.toggle("深色模式", key="dark_mode", value=False,
                  help="LIGHT / DARK 界面切换（参照专业数据站）")
        current = st.session_state.get("module", "schedule")
        default_label = next(f"{g} {name}" for code, name, g in MODULES if code == current)
        sel = st.radio("模块", MODULE_OPTS,
                       index=MODULE_OPTS.index(default_label), label_visibility="collapsed")
        module = MODULE_BY_LABEL.get(sel, current)
        st.session_state["module"] = module

        st.markdown('<div class="nav-group">全局筛选</div>', unsafe_allow_html=True)
        tables = load_tables()
        matches = tables["matches"]
        if not matches.empty:
            date_opts = sorted(matches["date"].dropna().astype(str).unique().tolist())
            team_opts = sorted(set(matches["team1"].dropna().astype(str)) |
                               set(matches["team2"].dropna().astype(str)))
            st.multiselect("比赛日期（空=全部）", date_opts, key="f_dates", width="stretch")
            st.multiselect("战队（空=全部）", team_opts, key="f_teams", width="stretch")
            st.toggle("仅已采集对局", key="f_cov", value=False)

        train = load_statuses().get("train") or {}
        model = str(train.get("version") or train.get("model_name") or "V11")
        st.markdown(
            f'<div class="side-foot">模型 <b>{_esc(model)}</b><br>'
            f'数据时钟 <b>{latest_data_time()}</b><br>'
            '战绩主源：腾讯 KPL 公开赛事接口</div>',
            unsafe_allow_html=True)
    return module


def context_chips() -> list[tuple[str, str]]:
    chips: list[tuple[str, str]] = []
    mid = st.session_state.get("drill_match")
    if mid:
        tables = load_tables()
        m = tables["matches"]
        row = m[m["match_id"] == mid]
        if not row.empty:
            r = row.iloc[0]
            chips.append(("大场", f"{r['date']} · {r['team1']} vs {r['team2']}"))
    team = st.session_state.get("team_sel")
    if team:
        chips.append(("战队", team))
    return chips


def main() -> None:
    st.set_page_config(page_title="KPL 数据中心", layout="wide",
                       initial_sidebar_state="expanded")
    # 注意：st.html 若“只有 <style>”会被 Streamlit 送到事件容器（临时），
    # 必须附带一个非 style 元素才会进入主文档；哨兵 div 用内联样式隐藏。
    st.html(build_css(bool(st.session_state.get("dark_mode", False)))
            + '<div style="display:none" class="css-sentinel"></div>')
    if "module" not in st.session_state:
        st.session_state["module"] = "schedule"

    tables = load_tables()
    matches, battles, teams, events = (
        tables["matches"], tables["battles"], tables["teams"], tables["events"])
    module = render_sidebar()
    train = load_statuses().get("train") or {}
    model = str(train.get("version") or train.get("model_name") or "V11")
    st.markdown(topbar_html(model), unsafe_allow_html=True)

    chips = context_chips()
    if chips:
        st.markdown(ctx_bar(chips), unsafe_allow_html=True)

    f_dates = st.session_state.get("f_dates") or []
    f_teams = st.session_state.get("f_teams") or []
    f_cov = st.session_state.get("f_cov", False)
    m, b = matches.copy(), battles.copy()
    if f_dates:
        m = m[m["date"].isin(f_dates)]
        b = b[b["date"].isin(f_dates)]
    if f_teams:
        b = b[b["team1"].isin(f_teams) | b["team2"].isin(f_teams)]
        m = m[m["match_id"].isin(b["match_id"].unique())]
    if f_cov and "has_timeline" in b.columns:
        b = b[b["has_timeline"].astype(bool)]
        m = m[m["match_id"].isin(b["match_id"].unique())]
    archive = load_archive()

    if module == "schedule":
        render_schedule(m, b, archive)
    elif module == "live":
        render_live()
    elif module == "replay":
        render_replay(m, b)
    elif module == "teams":
        render_teams(m, b, teams)
    elif module == "players":
        render_players()
    elif module == "heroes":
        render_heroes()
    elif module == "sim":
        render_sim()
    else:
        render_ops()

    st.markdown(
        '<div style="position:fixed;bottom:8px;right:18px;font-size:10px;color:var(--muted);'
        'font-family:var(--mono)">战绩主源：腾讯 KPL 公开赛事接口 · KPL DATA CENTER</div>',
        unsafe_allow_html=True)


if __name__ == "__main__":
    main()
