/* 峡谷有数 · 产品站公共层（v3）
   工具函数 / 图标 / 顶栏（含搜索）/ 页脚 / 动效 / 共用组件（曲线、对位、卡片、倒计时） */
window.KPL = (function () {
  "use strict";
  var D = window.SITE_DATA || null;
  var DT = window.SITE_DETAILS || { matches: [], teams: [], heroes: [] };

  /* ---------- 工具 ---------- */
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmtInt(n) { return Number(n || 0).toLocaleString("en-US"); }

  /* ---------- 最小匿名事件 ----------
     只上报事件名、路径、来源主机名和会话内随机 ID；不写 Cookie、不接收查询参数/选手名。
     生产端点见 worker.js（Cloudflare Analytics Engine）。本地/镜像站点直接跳过。 */
  var TRACK_EVENTS = {
    page_view: 1, match_open: 1, key_moment_click: 1, timeline_drag: 1, share_click: 1, fav_add: 1
  };
  function track(event) {
    try {
      if (!TRACK_EVENTS[event]) return;
      var host = location.hostname;
      if (/^(localhost|127\.0\.0\.1|\[::1\])$/.test(host) || /\.github\.io$/i.test(host)) return;
      var sid = "";
      try {
        sid = sessionStorage.getItem("kpl_sid") || "";
        if (!sid) {
          sid = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() :
            (Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
          sessionStorage.setItem("kpl_sid", sid);
        }
      } catch (e) { sid = ""; }
      var ref = "";
      try { ref = document.referrer ? new URL(document.referrer).hostname : ""; } catch (e) { ref = ""; }
      var body = JSON.stringify({
        e: event, p: String(location.pathname || "").split("?")[0], r: ref, s: sid
      });
      if (navigator.sendBeacon) {
        navigator.sendBeacon("/api/event", new Blob([body], { type: "application/json" }));
      } else if (window.fetch) {
        fetch("/api/event", { method: "POST", body: body, keepalive: true,
          headers: { "Content-Type": "application/json" } }).catch(function () {});
      }
    } catch (e) {}
  }
  function pct(v, d) { return (Number(v) * 100).toFixed(d == null ? 1 : d) + "%"; }
  function signed(v, d) { var n = Number(v); return (n >= 0 ? "+" : "") + n.toFixed(d == null ? 0 : d); }
  var WD = ["日", "一", "二", "三", "四", "五", "六"];
  function dateCN(iso) {
    var p = String(iso).split("-");
    return p.length === 3 ? parseInt(p[1], 10) + "月" + parseInt(p[2], 10) + "日" : String(iso);
  }
  function weekdayCN(iso) {
    var d = new Date(String(iso) + "T12:00:00");
    return isNaN(d) ? "" : "星期" + WD[d.getDay()];
  }
  /* 站点面向国内观众：所有“今天 / 现在”一律按 Asia/Shanghai 计算。
     直接用 toISOString() 会拿到 UTC 日期，北京时间 0–8 点会差一天。 */
  var CN_TZ = "Asia/Shanghai";
  function cnParts(d) {
    d = d || new Date();
    var out = {};
    try {
      new Intl.DateTimeFormat("en-GB", {
        timeZone: CN_TZ, year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hourCycle: "h23"
      }).formatToParts(d).forEach(function (x) { out[x.type] = x.value; });
    } catch (e) {
      var pad = function (n) { return String(n).padStart(2, "0"); };
      out = { year: String(d.getFullYear()), month: pad(d.getMonth() + 1), day: pad(d.getDate()),
              hour: pad(d.getHours()), minute: pad(d.getMinutes()) };
    }
    return out;
  }
  function cnDate(d) {
    var p = cnParts(d);
    return p.year + "-" + p.month + "-" + p.day;
  }
  function cnHM(d) {
    var p = cnParts(d);
    return p.hour + ":" + p.minute;
  }
  function todayCN() { return cnDate(new Date()); }
  function nowKeyCN() { var d = new Date(); return cnDate(d) + "T" + cnHM(d); }
  function tierOf(wr) { return wr >= 0.55 ? "S" : wr >= 0.50 ? "A" : wr >= 0.45 ? "B" : "C"; }

  /* ---------- 缺失值语义（全站统一） ----------
     null / undefined / 空串 / 非数 一律读作「无数据」，绝不自动变成 0；
     真实的 0（例如某段时间 MVP 率确实是 0）原样保留，正常显示为 0.0%。
     所有展示指标的地方都必须走这三个函数，禁止直接 Number(x || 0)。 */
  function mnum(v) {
    if (v === null || v === undefined) return null;
    if (typeof v === "string" && !v.trim()) return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }
  function mpct(v, d) { var n = mnum(v); return n === null ? "—" : n.toFixed(d == null ? 1 : d) + "%"; }
  function mnumText(v, d) { var n = mnum(v); return n === null ? "—" : n.toFixed(d == null ? 1 : d); }
  // 有效局数不足总局数时，把样本范围一并标出来（例：62.0%（8/10 局））
  function mfrac(v, validN, totalN) {
    var n = mnum(v);
    if (n === null) return "—";
    var s = n.toFixed(1) + "%";
    return (validN > 0 && totalN > 0 && validN < totalN) ? s + "（" + validN + "/" + totalN + " 局）" : s;
  }

  /* ---------- 图表调色板：随页面主题切换（v55 浅底页面用深色网格/更深的数据色） ---------- */
  function chartPalette() {
    var light = getComputedStyle(document.documentElement).colorScheme === "light";
    return light
      ? { grid: "#E3E5EA", axis: "#D9DCE2", label: "#6E7480", band: "#2E6FD0",
          line: "#2E6FD0", area: "#2E6FD0", mark: "#F02F55", onLine: "#191B23", dot: "#FFFFFF" }
      : { grid: "#283141", axis: "#41516B", label: "#A8B5C9", band: "#6EAFFF",
          line: "#6EAFFF", area: "#6EAFFF", mark: "#F07483", onLine: "#EDF0F7", dot: "#11141B" };
  }

  /* ---------- 全量赛程索引（assets/schedule_all.js）+ 赛段 / 赛制标签 ---------- */
  // 赛果行、赛程行、卡片都要显示「赛段 · 赛制」，统一从这里取，避免各页各算一套口径。
  var _ALL_IDX = null;
  function scheduleIndex() {
    if (_ALL_IDX) return _ALL_IDX;
    _ALL_IDX = {};
    (window.KPL_SCHEDULE_ALL || []).forEach(function (r) {
      if (r && r.matchId) _ALL_IDX[String(r.matchId)] = r;
    });
    return _ALL_IDX;
  }
  function matchMeta(matchId) {
    return scheduleIndex()[String(matchId == null ? "" : matchId)] || null;
  }
  // 历史数据里少数赛段存的是官方编码（fjs/tws…），补一层中文；其余原样返回。
  var STAGE_CN_EXTRA = {
    cgs1: "常规赛·第 1 轮", cgs2: "常规赛·第 2 轮", cgs3: "常规赛·第 3 轮",
    kws: "卡位赛", jhs: "季后赛", js: "决赛", zjs: "总决赛", lts: "擂台赛",
    dbtts: "单败淘汰赛", sbtts: "双败淘汰赛", fjs: "附加赛", tws: "突围赛", tts: "淘汰赛"
  };
  function stageLabel(stage) {
    var s = String(stage == null ? "" : stage);
    return STAGE_CN_EXTRA[s] || s;
  }
  function stageTags(matchId, opts) {
    var m = matchMeta(matchId);
    if (!m) return "";
    opts = opts || {};
    var t = [];
    if (opts.stage !== false && m.stage) t.push('<span class="stag">' + esc(stageLabel(m.stage)) + "</span>");
    if (opts.bo !== false && m.bo) t.push('<span class="bo mono">BO' + m.bo + "</span>");
    return t.length ? '<span class="mtags">' + t.join("") + "</span>" : "";
  }

  /* ---------- 赛事视图（当前届赛事 / 赛段进度 / 赛事积分榜） ----------
     首页头图、赛程页赛事条、赛事进程页共用同一套口径，避免各页各算一套。 */
  function _whenKey(r) { return String(r.date || "") + "T" + String(r.time || "00:00"); }
  function leagueRows(lid) {
    return (window.KPL_SCHEDULE_ALL || []).filter(function (r) { return r && String(r.leagueId) === String(lid); });
  }
  function leagueShortName(name) {
    return String(name || "").replace(/^\d{4}\s*年?\s*(KPL|王者荣耀)?\s*/, "");
  }
  function currentLeagueId() {
    var all = window.KPL_SCHEDULE_ALL || [];
    if (!all.length) return "";
    var pending = all.filter(function (r) { return !r.done; });
    var r = pending.length
      ? pending.slice().sort(function (a, b) { return _whenKey(a).localeCompare(_whenKey(b)); })[0]
      : all.slice().sort(function (a, b) { return _whenKey(a).localeCompare(_whenKey(b)); }).pop();
    return r ? String(r.leagueId || "") : "";
  }
  function leagueInfo(lid) {
    var rows = leagueRows(lid);
    if (!rows.length) return null;
    function span(list) {
      var ds = list.map(function (r) { return String(r.date || ""); }).sort();
      return { from: ds[0] || "", to: ds[ds.length - 1] || "" };
    }
    var stages = {}, order = [];
    rows.forEach(function (r) {
      var s = String(r.stage || "");
      if (!stages[s]) { stages[s] = []; order.push(s); }
      stages[s].push(r);
    });
    order.sort(function (a, b) { return span(stages[a]).from.localeCompare(span(stages[b]).from); });
    var list = order.map(function (s) {
      var st = stages[s], sp = span(st);
      var doneN = st.filter(function (r) { return r.done; }).length;
      return { key: s, label: stageLabel(s), rows: st, n: st.length, doneN: doneN,
               from: sp.from, to: sp.to, done: doneN === st.length };
    });
    var nowIdx = -1;
    for (var i = 0; i < list.length; i++) { if (!list[i].done) { nowIdx = i; break; } }
    var pending = rows.filter(function (r) { return !r.done; })
      .sort(function (a, b) { return _whenKey(a).localeCompare(_whenKey(b)); });
    var sp2 = span(rows);
    var last = rows.slice().sort(function (a, b) { return _whenKey(a).localeCompare(_whenKey(b)); }).pop();
    var s1 = last ? Number(last.score1 || 0) : 0, s2 = last ? Number(last.score2 || 0) : 0;
    var teams = {};
    rows.forEach(function (r) {
      if (r.team1 && r.team1 !== "待定") teams[r.team1] = 1;
      if (r.team2 && r.team2 !== "待定") teams[r.team2] = 1;
    });
    return {
      id: String(lid), name: String(rows[0].leagueName || lid), short: leagueShortName(rows[0].leagueName),
      year: String(rows[0].year || (sp2.from || "").slice(0, 4)),
      rows: rows, stages: list, nowIdx: nowIdx, total: rows.length,
      doneN: rows.filter(function (r) { return r.done; }).length,
      pending: pending, next: pending[0] || null,
      from: sp2.from, to: sp2.to, teamN: Object.keys(teams).length,
      champion: (nowIdx === -1 && last && last.done && (s1 || s2)) ? (s1 > s2 ? last.team1 : last.team2) : "",
    };
  }
  function leagueStandings(lid) {
    var st = {};
    function row(t) { return st[t] || (st[t] = { team: t, w: 0, l: 0, gw: 0, gl: 0, m: 0, icon: "" }); }
    leagueRows(lid).forEach(function (r) {
      if (!r.done || !r.team1 || !r.team2 || r.team1 === "待定" || r.team2 === "待定") return;
      var a = row(r.team1), b = row(r.team2);
      a.m++; b.m++;
      a.gw += Number(r.score1 || 0); a.gl += Number(r.score2 || 0);
      b.gw += Number(r.score2 || 0); b.gl += Number(r.score1 || 0);
      if (Number(r.score1) > Number(r.score2)) { a.w++; b.l++; } else { b.w++; a.l++; }
      if (r.icon1) a.icon = r.icon1;
      if (r.icon2) b.icon = r.icon2;
    });
    return Object.keys(st).map(function (t) { return st[t]; })
      .map(function (x) { x.diff = x.gw - x.gl; x.wr = x.gw / Math.max(1, x.gw + x.gl); return x; })
      .sort(function (x, y) { return (y.w - x.w) || (y.diff - x.diff) || (y.wr - x.wr); });
  }

  /* ---------- 图标（内联 SVG，stroke 现行色） ---------- */
  var ICONS = {
    home: '<path d="M4 11l8-7 8 7v9a1 1 0 01-1 1h-5v-6h-4v6H5a1 1 0 01-1-1z"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    shield: '<path d="M12 3l7 3v5c0 4.6-3 8.1-7 10-4-1.9-7-5.4-7-10V6z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4.2 5-6 8-6s6.5 1.8 8 6"/>',
    crown: '<path d="M4 18h16M5 18l-2-10 5.5 4L12 5l3.5 7L21 8l-2 10"/>',
    sliders: '<path d="M4 8h9M19 8h1M4 16h3M13 16h7"/><circle cx="15.5" cy="8" r="2.4"/><circle cx="9.5" cy="16" r="2.4"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/>',
    chart: '<path d="M4 20h16M7 20v-7M12 20V6M17 20v-10"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M4.5 12.5L12 16.7l7.5-4.2"/><path d="M4.5 16.5L12 20.7l7.5-4.2"/>',
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    pulse: '<path d="M3 12h4l2.5-6.5 4.5 13 2.5-6.5H21"/>',
    grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    github: '<path d="M12 2a10 10 0 00-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.9-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 015 0c1.9-1.29 2.74-1.02 2.74-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.75c0 .26.18.58.69.48A10 10 0 0012 2z" fill="currentColor" stroke="none"/>'
  };
  function icon(name, size) {
    var s = size || 18;
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      (ICONS[name] || "") + "</svg>";
  }

  /* ---------- 顶栏（含站内搜索） ----------
     V5 顶层导航只保留六组入口：赛事 / 战队 / 选手 / 英雄 / 分析 / 荣誉。
     活跃判定按「页面所属分组」的 data-page 集合匹配（不再靠 data-page 等于主链接）：
     detail 页（match/game/picks）沿用各自分组代表的 data-page，因此天然归组。 */
  var NAV = [
    { ic: "calendar", label: "赛事", href: "schedule.html",
      pages: ["index.html", "schedule.html", "bracket.html"],
      sub: [["赛程中心", "schedule.html"], ["赛事进程", "bracket.html"], ["精选对局", "picks.html"]] },
    { ic: "shield", label: "战队", href: "teams.html",
      pages: ["teams.html", "h2h.html"],
      sub: [["战队榜", "teams.html"], ["交手记录", "h2h.html"]] },
    { ic: "user", label: "选手", href: "players.html",
      pages: ["players.html"], sub: [] },
    { ic: "crown", label: "英雄", href: "heroes.html",
      pages: ["heroes.html", "combos.html"],
      sub: [["英雄列表", "heroes.html"], ["英雄组合", "combos.html"]] },
    { ic: "target", label: "分析", href: "bp.html",
      pages: ["bp.html", "bracket-forecast.html", "predict.html", "sandbox.html",
             "stage.html", "series.html", "compare.html", "compare-team.html",
             "compare-player.html", "compare-lane.html", "hero-performance.html", "team-bp.html", "coach.html",
             "comeback.html", "query.html", "find.html", "simulator.html"],
      sub: [["BP 分析", "bp.html"],
            ["英雄表现", "hero-performance.html"],
            ["战队 BP", "team-bp.html"],
            ["教练档案", "coach.html"],
            ["冠军预测", "bracket-forecast.html"],
            ["胜率沙盘", "sandbox.html"], ["系列赛研究", "series.html"], ["实时预测", "predict.html"],
            ["英雄对比", "compare.html"], ["战队对比", "compare-team.html"],
            ["选手对比", "compare-player.html"], ["位置对比", "compare-lane.html"],
            ["赛段对比", "stage.html"], ["翻盘研究所", "comeback.html"],
            ["数据查询", "query.html"], ["智能找局", "find.html"], ["赛前模拟", "simulator.html"]] },
    { ic: "layers", label: "荣誉", href: "honors.html",
      pages: ["honors.html", "records.html"],
      sub: [["荣誉中心", "honors.html"], ["赛事纪录", "records.html"]] }
  ];
  function navGroupHtml(page, real) {
    return NAV.map(function (g) {
      var on = g.pages.indexOf(page) >= 0;
      var sub = g.sub.length ? '<div class="nsub">' + g.sub.map(function (s) {
        return '<a href="' + s[1] + '"' + (s[1] === real ? ' class="subon"' : "") + ">" + esc(s[0]) + "</a>";
      }).join("") + "</div>" : "";
      // 有子菜单的顶级项只做“展开菜单”，不再跳转；主页面放在下拉第一项。
      var top = sub
        ? '<button class="ntop" type="button" data-href="' + g.href +
          '" aria-haspopup="true" aria-expanded="false">' +
          g.label + '<i class="caret"></i></button>'
        : '<a class="ntop" href="' + g.href + '" data-href="' + g.href + '">' + g.label + "</a>";
      return '<div class="ngrp' + (on ? " on" : "") + '">' + top + sub + "</div>";
    }).join("");
  }
  function topbar(page, real) {
    var links = navGroupHtml(page, real || page);
    return '<div class="wrap topbar-in">' +
      '<a class="brand" href="index.html"><span class="brand-mark">K</span>' +
      '<span class="brand-name">峡谷有数</span><span class="brand-sub">KPL INSIGHT</span></a>' +
      '<div class="search-wrap"><div class="search-box">' + icon("search", 16) +
      '<input id="siteSearch" placeholder="搜索战队 / 选手 / 英雄" autocomplete="off" spellcheck="false"></div>' +
      '<div class="search-pop" id="searchPop"></div></div>' +
      '<nav class="nav" id="siteNav">' + links + "</nav>" +
      '<button class="nav-toggle" id="navToggle" type="button" aria-label="打开导航" ' +
      'aria-expanded="false" aria-controls="siteNav">' + icon("menu", 19) + "</button>" +
      '<a class="gh-ico" href="https://github.com/hccccc01333/kpl-insight" target="_blank" rel="noopener" ' +
      'title="GitHub · 查看源码与 Star" aria-label="GitHub · 查看源码与 Star">' + icon("github", 19) + "</a></div>";
  }
  function footer() {
    return '<div class="wrap footer-in"><div>' +
      '<div class="foot-brand">峡谷有数 <span class="mono">/ KPL INSIGHT</span></div>' +
      '<p class="foot-note">数据来自腾讯王者荣耀职业联赛公开接口，为个人搭建的赛事数据产品（非官方、与腾讯无关联）。' +
      '统计均为自算口径：胜率类为历史区间估计，赛程与比分以官方发布为准。' +
      '了解数据口径与更新方式 → <a href="about.html" style="color:var(--gold)">数据说明</a></p></div>' +
      '<div class="foot-right mono"><div>数据更新 <b>' + esc(D ? D.generatedAt : "—") + "</b></div>" +
      '<a href="https://github.com/hccccc01333/kpl-insight" target="_blank" rel="noopener">GitHub · Star ↗</a>' +
      '<a href="https://github.com/hccccc01333/kpl-insight/issues" target="_blank" rel="noopener">反馈与贡献 ↗</a>' +
      '<a href="updates.html">更新日志</a>' +
      '<a href="about.html">数据说明 · 免责</a></div></div>';
  }

  /* ---------- 站内搜索（统一索引 · 全历史深链） ---------- */
  var SEARCH_INDEX = null;      // assets/search.js：战队/选手/英雄/2,884 场比赛
  var SEARCH_LOADING = false;
  function loadSearchIndex(cb) {
    if (SEARCH_INDEX) { cb(SEARCH_INDEX); return; }
    if (SEARCH_LOADING) return;
    SEARCH_LOADING = true;
    var sc = document.createElement("script");
    sc.src = "assets/search.js?ts=" + Date.now();
    sc.onload = function () {
      SEARCH_INDEX = window.KPL_SEARCH || [];
      SEARCH_LOADING = false;
      sc.remove();
      cb(SEARCH_INDEX);
    };
    sc.onerror = function () { SEARCH_LOADING = false; sc.remove(); };
    document.head.appendChild(sc);
  }

  function initSearch() {
    var input = document.getElementById("siteSearch");
    var pop = document.getElementById("searchPop");
    if (!input || !pop) return;
    // 首屏可用：用当前页已有的数据先兜底（秒出结果），完整索引按需懒加载
    var local = [];
    (D.standings || []).forEach(function (s) {
      local.push({ k: "战队", n: s.team, i: s.icon, h: "team.html?id=" + encodeURIComponent(s.team),
                   kw: (s.team || "").toLowerCase() });
    });
    var plist = (window.KPL_SEASONS && KPL_SEASONS.scopes && KPL_SEASONS.scopes.all.players) || D.players || [];
    plist.forEach(function (p) {
      local.push({ k: "选手", n: p.name + " · " + p.team, i: p.icon || p.teamIcon,
                   h: "player.html?id=" + encodeURIComponent(p.name), kw: (p.name + " " + p.team).toLowerCase() });
    });
    (D.heroes || []).forEach(function (h) {
      local.push({ k: "英雄", n: h.name, i: h.icon, h: "hero.html?id=" + encodeURIComponent(h.name),
                   kw: (h.name || "").toLowerCase() });
    });
    (D.schedule || []).slice(0, 200).forEach(function (r) {
      local.push({ k: "比赛", n: r.team1 + " vs " + r.team2, i: r.icon1 || "",
                   h: "match.html?id=" + encodeURIComponent(r.matchId),
                   kw: (r.team1 + " " + r.team2 + " " + r.date).toLowerCase() });
    });

    function pool() {
      if (!SEARCH_INDEX) return local;
      var out = local.slice(), seen = {};
      local.forEach(function (it) { seen[it.h + "|" + it.n] = 1; });
      SEARCH_INDEX.forEach(function (it) {
        var key = it.h + "|" + it.n;
        if (seen[key]) return;
        seen[key] = 1;
        out.push({ k: it.k, n: it.n, i: it.i, h: it.h, kw: ((it.n || "") + " " + (it.s || "")).toLowerCase() });
      });
      return out;
    }

    function render(q) {
      if (!q) { pop.classList.remove("on"); pop.innerHTML = ""; return; }
      var ql = q.toLowerCase();
      var hits = pool().filter(function (it) { return it.kw.indexOf(ql) >= 0; });
      // 名称前缀 > 名称包含 > 关键词命中，同级保持索引顺序（比赛按时间倒序）
      hits.sort(function (a, b) {
        return rankOf(a.n, ql) - rankOf(b.n, ql);
      });
      var shown = hits.slice(0, 12);
      pop.innerHTML = shown.length
        ? shown.map(function (h) {
            return '<a href="' + esc(h.h) + '">' + (h.i ? '<img src="' + esc(h.i) + '" alt="">' : "") +
              "<span>" + esc(h.n) + '</span><span class="k">' + esc(h.k) + "</span></a>";
          }).join("") +
          (hits.length > shown.length
            ? '<a><span style="color:var(--muted)">还有 ' + (hits.length - shown.length) + " 条结果，输入更多关键词缩小范围</span></a>"
            : "")
        : '<a><span style="color:var(--muted)">没有匹配结果</span></a>';
      pop.classList.add("on");
    }
    function rankOf(name, ql) {
      var n = String(name || "").toLowerCase();
      if (n.indexOf(ql) === 0) return 0;
      if (n.indexOf(ql) >= 0) return 1;
      return 2;
    }
    function refreshFromIndex() {
      if (SEARCH_INDEX) render(input.value.trim());
    }
    // 输入时懒加载完整索引，加载完自动补一次渲染
    input.addEventListener("input", function () {
      render(input.value.trim());
      loadSearchIndex(refreshFromIndex);
    });
    input.addEventListener("focus", function () {
      render(input.value.trim());
      loadSearchIndex(refreshFromIndex);
    });
    document.addEventListener("click", function (e) {
      if (!e.target.closest(".search-wrap")) pop.classList.remove("on");
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        var first = pop.querySelector("a[href]");
        if (first) location.href = first.getAttribute("href");
      }
    });
  }

  /* ---------- 移动端导航抽屉 ---------- */
  function initNav() {
    var btn = document.getElementById("navToggle");
    var nav = document.getElementById("siteNav");
    if (!btn || !nav) return;
    var openIcon = icon("menu", 19), closeIcon = icon("close", 19);
    function setOpen(open) {
      nav.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      btn.setAttribute("aria-label", open ? "关闭导航" : "打开导航");
      btn.innerHTML = open ? closeIcon : openIcon;
    }
    function closeGroups(except) {
      nav.querySelectorAll(".ngrp.open").forEach(function (g) {
        if (g === except) return;
        g.classList.remove("open");
        var b = g.querySelector("button.ntop");
        if (b) b.setAttribute("aria-expanded", "false");
      });
    }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      setOpen(!nav.classList.contains("open"));
    });
    nav.addEventListener("click", function (e) {
      var parent = e.target.closest("button.ntop");
      if (parent) {
        e.preventDefault();
        var grp = parent.parentNode;
        var was = grp.classList.contains("open");
        closeGroups(null);
        if (!was) {
          grp.classList.add("open");
          parent.setAttribute("aria-expanded", "true");
        }
        return;
      }
      if (e.target.closest("a")) setOpen(false);
    });
    document.addEventListener("click", function (e) {
      if (!nav.contains(e.target) && !btn.contains(e.target)) {
        setOpen(false);
        closeGroups(null);
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        setOpen(false);
        closeGroups(null);
      }
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 900) {
        setOpen(false);
        closeGroups(null);
      }
    });
  }

  /* ---------- 收藏 / 关注（localStorage，无需账户） ---------- */
  var FAV_KEY = "kpl_fav_v1";
  function favList() {
    try { return JSON.parse(localStorage.getItem(FAV_KEY) || "[]") || []; } catch (e) { return []; }
  }
  function favSave(list) {
    try { localStorage.setItem(FAV_KEY, JSON.stringify(list.slice(0, 60))); } catch (e) {}
  }
  function favHas(kind, id) {
    return favList().some(function (f) { return f.kind === kind && f.id === id; });
  }
  function favToggle(item) {
    var list = favList();
    var i = -1;
    for (var k = 0; k < list.length; k++) if (list[k].kind === item.kind && list[k].id === item.id) { i = k; break; }
    if (i >= 0) list.splice(i, 1); else list.unshift(item);
    favSave(list);
    return i < 0;
  }
  /* 星标按钮：kind = team|player|match */
  function favBtn(item) {
    var on = favHas(item.kind, item.id);
    return '<button type="button" class="fav-btn' + (on ? " on" : "") + '" data-kind="' + esc(item.kind) +
      '" data-id="' + esc(item.id) + '" data-label="' + esc(item.label || item.id) +
      '" data-icon="' + esc(item.icon || "") + '" data-href="' + esc(item.href || "") + '" ' +
      'aria-pressed="' + (on ? "true" : "false") + '" title="' + (on ? "取消收藏" : "收藏") + '">' +
      (on ? "★ 已收藏" : "☆ 收藏") + "</button>";
  }
  function initFav() {
    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".fav-btn");
      if (!btn) return;
      e.preventDefault();
      var item = {
        kind: btn.getAttribute("data-kind"), id: btn.getAttribute("data-id"),
        label: btn.getAttribute("data-label"), icon: btn.getAttribute("data-icon"),
        href: btn.getAttribute("data-href")
      };
      var nowOn = favToggle(item);
      if (nowOn) track("fav_add");
      btn.classList.toggle("on", nowOn);
      btn.setAttribute("aria-pressed", nowOn ? "true" : "false");
      btn.textContent = nowOn ? "★ 已收藏" : "☆ 收藏";
      btn.title = nowOn ? "取消收藏" : "收藏";
      var strip = document.getElementById("favStrip");
      if (strip) renderFavStrip(strip);
    });
  }
  function renderFavStrip(el) {
    if (!el) return;
    var list = favList();
    if (!list.length) { el.innerHTML = ""; el.style.display = "none"; return; }
    el.style.display = "";
    el.innerHTML = '<div class="fav-strip"><div class="fav-cap mono">我的关注 ' + list.length + '</div>' +
      '<div class="fav-items">' + list.map(function (f) {
        var href = f.href || "index.html";
        return '<a class="fav-chip" href="' + esc(href) + '">' +
          (f.icon ? '<img src="' + esc(f.icon) + '" alt="">' : "") + esc(f.label) +
          '<span class="k">' + esc(f.kind === "team" ? "战队" : f.kind === "player" ? "选手" : "比赛") + "</span></a>";
      }).join("") + "</div></div>";
  }

  /* ---------- 数据完整度徽标（V4：点进去之前就知道能看到什么） ---------- */
  // mask: bit0 比分 · bit1 完整BP · bit2 选手明细 · bit3 分钟级曲线 · bit4 模型估算
  // 「模型」徽标曾独立存在，但它的判定条件（有重放包且有概率）与「分钟级」完全一致，
  // 独立展示只会让用户以为是两件事 —— 合并成一枚，说明里写清"含模型胜率曲线"。
  var COV_ITEMS = [
    ["比分", 1, "官方比分与用时"],
    ["BP", 2, "完整 BP（双方 10 个选人）"],
    ["选手", 4, "逐局选手数据（KDA / 经济 / 出装）"],
    ["分钟级", 24, "逐分钟经济 / 资源 / 击杀序列，含模型胜率曲线（估算）"]
  ];

  function coverageMask(matchId) {
    var cov = window.KPL_COVERAGE || {};
    return typeof cov[matchId] === "number" ? cov[matchId] : 0;
  }

  function battleCoverageMask(matchId, battleId) {
    var mask = 0;
    var g = (window.KPL_GAME_INDEX || {})[matchId];
    if (g) {
      for (var i = 0; i < (g.b || []).length; i++) {
        var row = g.b[i];
        if (row[0] === battleId) {
          var flags = Number(row[5] || 0);
          mask |= 1;
          if (flags & 1) mask |= 2;
          if (flags & 2) mask |= 4;
          break;
        }
      }
    }
    var rp = (window.KPL_REPLAY_INDEX || {})[matchId];
    if (rp) {
      var idx = (rp.b || []).indexOf(battleId);
      if (idx >= 0) {
        mask |= 8;
        if ((rp.p || [])[idx]) mask |= 16;
      }
    }
    return mask;
  }

  /* 渲染徽标：on 为高亮，缺失项灰显并标明"无" */
  function coverageBadges(mask, opts) {
    opts = opts || {};
    var onlyMissing = !!opts.onlyMissing;
    var items = COV_ITEMS.filter(function (it) { return !onlyMissing || !(mask & it[1]); });
    if (!items.length) return "";
    return '<span class="cov">' + items.map(function (it) {
      var on = !!(mask & it[1]);
      return '<span class="cov-i ' + (on ? "on" : "off") + '" title="' +
        esc(it[0]) + "：" + (on ? esc(it[2]) : "本局无此数据") + '">' + esc(it[0]) + "</span>";
    }).join("") + "</span>";
  }

  /* ---------- 共用渲染 ---------- */
  function side(team, ic, r) {
    return '<div class="side' + (r ? " r" : "") + '">' +
      (r && ic ? '<img src="' + esc(ic) + '" alt="" loading="lazy">' : "") +
      "<span>" + esc(team) + "</span>" +
      (!r && ic ? '<img src="' + esc(ic) + '" alt="" loading="lazy">' : "") + "</div>";
  }
  function resultRow(r, opts) {
    var ok = r.score1 >= 0 && r.score2 >= 0;
    var s1 = ok ? '<span class="' + (r.score1 >= r.score2 ? "w" : "") + '">' + r.score1 + "</span>" : "–";
    var s2 = ok ? '<span class="' + (r.score2 > r.score1 ? "w" : "") + '">' + r.score2 + "</span>" : "–";
    var go = '<a class="go" href="match.html?id=' + esc(r.matchId) + '">' +
      (coverageMask(r.matchId) & 8 ? "复盘" : "详情") + "</a>";
    // opts.badges：列表里顺带显示数据完整度（首页最新结果用）
    var cov = (opts && opts.badges) ? '<span class="row-cov">' + coverageBadges(coverageMask(r.matchId)) + "</span>" : "";
    // 赛段 · 赛制：此前赛果行拿不到，现在统一从全量赛程索引补齐（同源，口径一致）
    var m = matchMeta(r.matchId) || {};
    var metaBits = [];
    if (m.stage) metaBits.push(esc(stageLabel(m.stage)));
    if (m.bo) metaBits.push("BO" + m.bo);
    var meta = metaBits.length ? '<em class="rt-meta" title="' + metaBits.join(" · ") + '">' +
      metaBits.join(" · ") + "</em>" : "";
    return '<div class="row" data-mid="' + esc(String(r.matchId || "")) + '">' +
      '<div class="rt-date"><b>' + esc(dateCN(r.date)) + "</b>" + esc(weekdayCN(r.date)) + meta + "</div>" +
      side(r.team1, r.icon1, false) +
      '<div class="score">' + s1 + " : " + s2 + "</div>" +
      side(r.team2, r.icon2, true) + cov + go + "</div>";
  }
  function muBody(rows) {
    return rows.length ? rows.map(function (r) {
      var tag = r.n < 8 ? '<span class="chip">样本不足</span>' : '<span class="chip done">样本充足</span>';
      return "<tr>" +
        '<td><span class="team-cell">' + (r.blueIcon ? '<img src="' + esc(r.blueIcon) + '" alt="">' : "") + esc(r.blue) + "</span></td>" +
        '<td><span class="team-cell">' + (r.redIcon ? '<img src="' + esc(r.redIcon) + '" alt="">' : "") + esc(r.red) + "</span></td>" +
        '<td class="num">' + r.n + " 局</td>" +
        '<td class="num">' + pct(r.wr) + "</td>" +
        '<td class="mono" style="font-size:12px;color:var(--muted)">' + pct(r.ciLo, 0) + " – " + pct(r.ciHi, 0) + "</td>" +
        "<td>" + tag + "</td></tr>";
    }).join("") : '<tr><td colspan="6" style="color:var(--muted)">该位置暂无可展示对位</td></tr>';
  }
  function heroCard(h, i) {
    var banTxt = h.banRate != null ? pct(h.banRate, 0)
      : (h.bans != null ? pct(h.bans / Math.max(1, h.games + h.bans), 0) : "—");
    return '<a class="hcard reveal" style="transition-delay:' + Math.min((i || 0) * 25, 300) +
      'ms" href="hero.html?id=' + encodeURIComponent(h.name) + '" ' +
      'title="' + esc(h.name) + " · " + h.games + " 局 · 胜率 " + pct(h.wr) + '">' +
      (h.icon ? '<img src="' + esc(h.icon) + '" alt="" loading="lazy">' : "") +
      '<div class="nm">' + esc(h.name) + '<span class="tier ' + h.tier + '">' + h.tier + "</span></div>" +
      '<div class="wr"><span>胜率</span><b class="mono">' + pct(h.wr) + "</b></div>" +
      '<div class="minibar"><i style="width:' + (h.wr * 100).toFixed(1) + '%"></i></div>' +
      '<div class="sub">出场 ' + h.games + " · 禁用 " + banTxt + "</div></a>";
  }
  function playerCard(p, i) {
    var ava = p.icon ? '<img class="p-ava" src="' + esc(p.icon) + '" alt="" loading="lazy">'
      : '<span class="p-ava ph">' + esc(String(p.name).slice(0, 1)) + "</span>";
    return '<div class="player reveal" id="pl-' + esc(p.name) + '" style="transition-delay:' +
      Math.min((i || 0) * 30, 240) + 'ms">' + ava +
      '<div class="p-main"><div class="p-top">' +
      '<span class="p-name"><span class="nm">' + esc(p.name) + "</span><em>" + esc(p.pos) + "</em></span>" +
      '<span class="p-kda">' + mnumText(p.kda, 1) + "<small>KDA</small></span></div>" +
      '<div class="p-team">' + (p.teamIcon ? '<img src="' + esc(p.teamIcon) + '" alt="">' : "") +
      "<b>" + esc(p.team) + "</b><span>· " + p.games + " 局 · MVP " + p.mvp + " · 参团 " + mpct(p.part, 0) + "</span></div>" +
      "</div></div>";
  }

  /* ---------- 胜率曲线（深色主题） ---------- */
  function wrChart(el, F, team1) {
    var tl = (F && F.key ? F.key.timeline : (F ? F.timeline : [])) || [];
    var phases = (F && F.key ? F.key.phases : (F ? F.phases : [])) || [];
    var events = (F && F.key ? F.key.events : (F ? F.events : [])) || [];
    var CP = chartPalette();
    if (!el || tl.length < 2) { if (el) el.innerHTML = '<div class="empty-tip">该局无分钟级曲线</div>'; return; }
    var W = 1040, H = 300, P = { l: 48, r: 18, t: 22, b: 34 };
    var fc = (F && F.forecast) || [];
    var maxM = Math.max(16, tl[tl.length - 1].m, fc.length ? fc[fc.length - 1][0] : 0);
    var X = function (m) { return P.l + (m / maxM) * (W - P.l - P.r); };
    var Y = function (p) { return P.t + (1 - p) * (H - P.t - P.b); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" aria-label="胜率曲线">';
    s += '<defs><linearGradient id="gdarea" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color=' + JSON.stringify(CP.area) + ' stop-opacity=".34"/>' +
      '<stop offset="1" stop-color=' + JSON.stringify(CP.area) + ' stop-opacity="0"/></linearGradient></defs>';
    var phLabels = ["早期 ≤8′", "中期 9–15′", "后期 16′+"];
    phases.forEach(function (ph, i) {
      var lo = i === 0 ? 0 : phases[i - 1].last_minute;
      s += '<rect x="' + X(lo).toFixed(1) + '" y="' + P.t + '" width="' + (X(ph.last_minute) - X(lo)).toFixed(1) +
        '" height="' + (H - P.t - P.b) + '" fill=' + JSON.stringify(CP.band) + ' opacity="0.05"/>' +
        '<text x="' + ((X(lo) + X(ph.last_minute)) / 2).toFixed(1) + '" y="' + (P.t + 13) +
        '" text-anchor="middle" font-size="11" fill=' + JSON.stringify(CP.label) + ' font-family="Roboto Mono,monospace">' + (phLabels[i] || "") + "</text>";
    });
    [0, 0.25, 0.5, 0.75, 1].forEach(function (p) {
      var y = Y(p);
      s += '<line class="gridline" x1="' + P.l + '" y1="' + y.toFixed(1) + '" x2="' + (W - P.r) + '" y2="' + y.toFixed(1) +
        '" stroke=' + JSON.stringify(CP.grid) + ' stroke-dasharray="' + (p === 0.5 ? "4 4" : "2 6") + '"/>' +
        '<text x="' + (P.l - 9) + '" y="' + (y + 4).toFixed(1) +
        '" text-anchor="end" font-size="11" fill=' + JSON.stringify(CP.label) + ' font-family="Roboto Mono,monospace">' + Math.round(p * 100) + "%</text>";
    });
    for (var m = 5; m <= maxM; m += 5) {
      s += '<text x="' + X(m).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle" font-size="11" ' +
        'fill=' + JSON.stringify(CP.label) + ' font-family="Roboto Mono,monospace">' + m + "′</text>";
    }
    var line = tl.map(function (pt, i) { return (i ? "L" : "M") + X(pt.m).toFixed(1) + "," + Y(pt.p).toFixed(1); }).join(" ");
    s += '<path d="' + line + " L" + X(tl[tl.length - 1].m).toFixed(1) + "," + (H - P.b) +
      " L" + X(tl[0].m).toFixed(1) + "," + (H - P.b) + ' Z" fill="url(#gdarea)"/>';
    s += '<path id="wrLine" d="' + line + '" fill="none" stroke=' + JSON.stringify(CP.line) + ' stroke-width="2.8" ' +
      'stroke-linejoin="round" stroke-linecap="round"/>';
    var EV_COLOR = { first_blood: "#C08A8D", tyrant: "#8FB3AE", dark_tyrant: "#8FB3AE", lord: "#FFFFFF", storm: "#FFFFFF", big_dragon: "#FFFFFF" };
    var shown = 0;
    var probAt = function (mm) {
      var best = tl[0];
      for (var i = 0; i < tl.length; i++) if (Math.abs(tl[i].m - mm) < Math.abs(best.m - mm)) best = tl[i];
      return best.p;
    };
    events.forEach(function (e) {
      var c = EV_COLOR[e.type];
      if (!c || shown >= 26) return;
      shown++;
      s += '<circle cx="' + X(Math.min(e.m, maxM)).toFixed(1) + '" cy="' + Y(probAt(e.m)).toFixed(1) +
        '" r="3.4" fill="' + c + '" opacity="0.95"><title>' + esc(e.m.toFixed(0) + "′ " + e.label) + "</title></circle>";
    });
    /* 未来预测段（金色虚线）：从当前点延伸到预测点 */
    if (fc.length && tl.length) {
      var lastPt = tl[tl.length - 1];
      var fcPts = [[lastPt.m, lastPt.p]].concat(fc);
      var fd = fcPts.map(function (pt, i) {
        return (i ? "L" : "M") + X(pt[0]).toFixed(1) + " " + Y(pt[1]).toFixed(1);
      }).join(" ");
      s += '<path d="' + fd + '" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-dasharray="6 5" opacity=".9"/>';
      fc.forEach(function (pt) {
        s += '<circle cx="' + X(pt[0]).toFixed(1) + '" cy="' + Y(pt[1]).toFixed(1) + '" r="3.2" fill="#FFFFFF" opacity=".9"/>' +
          '<text x="' + X(pt[0]).toFixed(1) + '" y="' + (Y(pt[1]) - 9).toFixed(1) + '" text-anchor="middle" font-size="10.5" fill="#FFFFFF" font-family="Inter,monospace">' +
          Math.round(pt[1] * 100) + "%</text>";
      });
    }
    s += '<g id="wrCross" style="display:none"><line y1="' + P.t + '" y2="' + (H - P.b) +
      '" stroke="#FFFFFF" stroke-width="1" stroke-dasharray="3 3"/>' +
      '<circle r="4.6" fill="#0A111C" stroke="#FFFFFF" stroke-width="2.4"/></g></svg>';
    el.innerHTML = s;

    var svg = el.querySelector("svg");
    var cross = svg.querySelector("#wrCross");
    var cline = cross.querySelector("line"), cdot = cross.querySelector("circle");
    var tip = document.createElement("div");
    tip.className = "chart-tip mono";
    el.appendChild(tip);
    svg.addEventListener("mousemove", function (ev) {
      var r = svg.getBoundingClientRect();
      var xRatio = (ev.clientX - r.left) / r.width * W;
      var m = Math.max(0, Math.min(maxM, ((xRatio - P.l) / (W - P.l - P.r)) * maxM));
      var near = tl[0];
      tl.forEach(function (pt) { if (Math.abs(pt.m - m) < Math.abs(near.m - m)) near = pt; });
      var x = X(near.m), y = Y(near.p);
      cross.style.display = "";
      cline.setAttribute("x1", x); cline.setAttribute("x2", x);
      cdot.setAttribute("cx", x); cdot.setAttribute("cy", y);
      tip.style.display = "block";
      tip.textContent = near.m.toFixed(0) + "′ · " + team1 + "胜率 " + pct(near.p, 0) + " · 金差 " + signed(near.gd);
      tip.style.left = Math.min(r.width - tip.offsetWidth - 8, (x / W) * r.width + 12) + "px";
      tip.style.top = Math.max(0, (y / H) * r.height - 36) + "px";
    });
    svg.addEventListener("mouseleave", function () {
      cross.style.display = "none"; tip.style.display = "none";
    });
    var lineEl = svg.querySelector("#wrLine");
    var len = lineEl.getTotalLength();
    lineEl.style.strokeDasharray = len;
    lineEl.style.strokeDashoffset = len;
    var io = new IntersectionObserver(function (es) {
      if (es[0].isIntersecting) {
        lineEl.style.transition = "stroke-dashoffset .9s ease-out";
        lineEl.style.strokeDashoffset = 0;
        io.disconnect();
      }
    }, { threshold: 0.25 });
    io.observe(svg);
  }

  /* ---------- 倒计时 ---------- */
  function countdown(targetMs, el) {
    function tick() {
      var diff = targetMs - Date.now();
      if (!el) return;
      if (diff <= 0) { el.textContent = "已开始"; return; }
      var d = Math.floor(diff / 86400000), h = Math.floor(diff % 86400000 / 3600000),
          m = Math.floor(diff % 3600000 / 60000), sec = Math.floor(diff % 60000 / 1000);
      el.textContent = (d > 0 ? d + " 天 " : "") + h + " 小时 " + m + " 分 " + (d > 0 ? "" : sec + " 秒");
    }
    tick();
    return setInterval(tick, 1000);
  }

  /* ---------- 初始化（可重复 scan） ---------- */
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var revealObs = null, countObs = null;

  function countUp(el) {
    var target = parseFloat(el.getAttribute("data-count")),
        dec = parseInt(el.getAttribute("data-dec") || "0", 10);
    if (isNaN(target)) return;
    if (reduce) { el.textContent = dec ? target.toFixed(dec) : fmtInt(target); return; }
    var t0 = null, dur = 800;
    (function tick(ts) {
      if (!t0) t0 = ts || performance.now();
      var k = Math.min(1, ((ts || performance.now()) - t0) / dur);
      var v = target * (1 - Math.pow(1 - k, 3));
      el.textContent = dec ? v.toFixed(dec) : fmtInt(Math.round(v));
      if (k < 1) requestAnimationFrame(tick);
    })();
  }

  function scan() {
    if (!revealObs && !reduce && "IntersectionObserver" in window) {
      revealObs = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); revealObs.unobserve(e.target); } });
      }, { rootMargin: "0px 0px -8% 0px" });
    }
    document.querySelectorAll(".reveal:not([data-anim])").forEach(function (x) {
      x.setAttribute("data-anim", "1");
      if (revealObs) revealObs.observe(x); else x.classList.add("in");
    });
    if (!countObs && !reduce && "IntersectionObserver" in window) {
      countObs = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) { countUp(e.target); countObs.unobserve(e.target); } });
      }, { threshold: 0.4 });
    }
    document.querySelectorAll("[data-count]:not([data-counted])").forEach(function (x) {
      x.setAttribute("data-counted", "1");
      if (countObs) countObs.observe(x); else countUp(x);
    });
  }

  function init() {
    var page = document.body.getAttribute("data-page") || "index.html";
    var real = (location.pathname.split("/").pop() || "").toLowerCase();
    if (!/\.html$/.test(real)) real = page;
    var h = document.getElementById("siteHeader");
    var f = document.getElementById("siteFooter");
    if (h) {
      h.classList.add("topbar");
      h.innerHTML = topbar(page, real);
    }
    if (f) f.innerHTML = footer();
    initSearch();
    initNav();
    initFav();
    scan();
    autoRefresh();
    track("page_view");
    var pathName = (location.pathname.split("/").pop() || "").toLowerCase();
    if (/^(match|game)(\.html)?$/.test(pathName)) track("match_open");
  }

  /* ---------- CSV 导出 ---------- */
  function exportCSV(filename, rows) {
    var csv = rows.map(function (r) {
      return r.map(function (c) {
        c = String(c == null ? "" : c);
        return /[",\n]/.test(c) ? '"' + c.replace(/"/g, '""') + '"' : c;
      }).join(",");
    }).join("\r\n");
    var blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }


  /* ---------- 数据简报（动态一句话结论） ---------- */
  function brief(mount, html) {
    var el = typeof mount === "string" ? document.querySelector(mount) : mount;
    if (!el) return;
    el.innerHTML = '<span class="ico">●</span><p>' + html + "</p>";
  }

  /* ---------- 多系列折线图（指标曲线） ---------- */
  function lineChart(el, opts) {
    var CP2 = chartPalette();
    if (!el) return;
    var series = (opts.series || []).filter(function (se) { return se.pts && se.pts.length > 1; });
    if (!series.length) { el.innerHTML = '<div class="empty-tip">暂无可展示的曲线</div>'; return; }
    var W = 1040, H = opts.height || 280, P = { l: 62, r: 18, t: 20, b: 34 };
    var xs = [], ys = [];
    series.forEach(function (se) {
      se.pts.forEach(function (pt) { xs.push(pt[0]); ys.push(pt[1]); });
    });
    var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
    var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
    if (opts.yZero) { yMin = Math.min(0, yMin); yMax = Math.max(0, yMax); }
    if (opts.yMin0) { yMin = Math.max(0, yMin); }
    var pad = (yMax - yMin) * 0.08 || 1;
    yMin -= pad; yMax += pad;
    if (xMax - xMin < 1) xMax = xMin + 1;
    var X = function (v) { return P.l + (v - xMin) / (xMax - xMin) * (W - P.l - P.r); };
    var Y = function (v) { return P.t + (1 - (v - yMin) / (yMax - yMin)) * (H - P.t - P.b); };
    var yFmt = opts.yFmt || function (v) { return Math.round(v); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img">';
    /* 网格与 y 轴 */
    for (var gi = 0; gi <= 3; gi++) {
      var gv = yMin + (yMax - yMin) * gi / 3;
      var gy = Y(gv).toFixed(1);
      s += '<line x1="' + P.l + '" y1="' + gy + '" x2="' + (W - P.r) + '" y2="' + gy +
        '" stroke=' + JSON.stringify(CP2.grid) + ' stroke-dasharray="4 6"/>' +
        '<text x="' + (P.l - 8) + '" y="' + (parseFloat(gy) + 4) + '" text-anchor="end" font-size="10.5" fill=' + JSON.stringify(CP2.label) + ' font-family="Inter,monospace">' + yFmt(gv) + "</text>";
    }
    if (yMin < 0 && yMax > 0) {
      s += '<line x1="' + P.l + '" y1="' + Y(0).toFixed(1) + '" x2="' + (W - P.r) + '" y2="' + Y(0).toFixed(1) + '" stroke=' + JSON.stringify(CP2.axis) + ' />';
    }
    /* x 轴刻度（每 5 分钟） */
    for (var m = Math.ceil(xMin / 5) * 5; m <= xMax; m += 5) {
      s += '<text x="' + X(m).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle" font-size="10.5" fill=' + JSON.stringify(CP2.label) + ' font-family="Inter,monospace">' + m + "′</text>";
    }
    /* 折线 */
    series.forEach(function (se) {
      var d = se.pts.map(function (pt, i) {
        return (i ? "L" : "M") + X(pt[0]).toFixed(1) + " " + Y(pt[1]).toFixed(1);
      }).join(" ");
      if (se.fill && se.pts.length > 1) {
        s += '<path d="' + d + " L" + X(se.pts[se.pts.length - 1][0]).toFixed(1) + " " + Y(Math.max(0, yMin)).toFixed(1) +
          " L" + X(se.pts[0][0]).toFixed(1) + " " + Y(Math.max(0, yMin)).toFixed(1) + ' Z" fill="' + se.color + '" fill-opacity=".10" stroke="none"/>';
      }
      s += '<path d="' + d + '" fill="none" stroke="' + se.color + '" stroke-width="' + (se.width || 2.2) + '"' +
        (se.dash ? ' stroke-dasharray="6 5"' : "") + ' stroke-linejoin="round" opacity="' + (se.opacity || 1) + '"/>';
      if (se.dots) {
        se.pts.forEach(function (pt) {
          s += '<circle cx="' + X(pt[0]).toFixed(1) + '" cy="' + Y(pt[1]).toFixed(1) + '" r="2.6" fill="' + se.color + '"/>';
        });
      }
    });
    s += "</svg>";
    el.innerHTML = (opts.legend === false ? "" :
      '<div class="lc-legend">' + series.map(function (se) {
        return '<span><i style="background:' + se.color + (se.dash ? ';opacity:.65' : "") + '"></i>' + esc(se.name) + "</span>";
      }).join("") + "</div>") + s;
  }

  /* ---------- 实时框架：数据新鲜度探测 + 进行中判定 ---------- */
  var LIVE_WINDOW_MS = 3.5 * 3600 * 1000; // 开赛后 3.5 小时内视为进行中

  function isLive(r) {
    if (!r || r.done || !r.date) return false;
    var t = new Date(r.date + "T" + (r.time || "17:00") + ":00").getTime();
    var now = Date.now();
    return now >= t && now <= t + LIVE_WINDOW_MS;
  }

  function liveBadge() {
    return '<span class="chip live"><i></i>进行中</span>';
  }

  function showUpdateBar(at) {
    if (document.getElementById("updateBar")) return;
    var bar = document.createElement("div");
    bar.id = "updateBar";
    bar.innerHTML = '<span>检测到新数据（' + esc(at) + "），刷新查看最新赛况</span>" +
      '<button type="button">立即刷新</button>';
    bar.querySelector("button").addEventListener("click", function () { location.reload(); });
    document.body.appendChild(bar);
  }

  var _refreshTimer = null;
  function autoRefresh() {
    if (_refreshTimer || !D || !D.generatedAt) return;
    var cur = String(D.generatedAt);
    _refreshTimer = setInterval(function () {
      fetch("assets/data.js?ts=" + Date.now()).then(function (r) { return r.text(); })
        .then(function (txt) {
          var m = txt.match(/"generatedAt"\s*:\s*"([^"]+)"/);
          if (m && m[1] && m[1] !== cur) showUpdateBar(m[1]);
        }).catch(function () {});
    }, 90000);
  }

  /* ---------- 数据范围选择器（年份 × 赛事） ---------- */
  var SCOPE_KEY = "kpl_scope_v1";

  function scopeOf(id) {
    var S = window.KPL_SEASONS;
    if (!S) return null;
    return S.scopes[id] || S.scopes["all"] || null;
  }

  function scopeName(id) {
    var S = window.KPL_SEASONS;
    if (!S || id === "all") return "全部年份";
    if (/^\d{4}$/.test(id)) return id + " 年";
    var lg = (S.leagues || []).filter(function (l) { return l.id === id; })[0];
    return lg ? lg.name : id;
  }

  function scopeMeta(id) {
    var d = scopeOf(id);
    if (!d) return "";
    return "共 " + fmtInt(d.totals.matches) + " 场比赛 · " + fmtInt(d.totals.battles) + " 局";
  }

  /* 渲染 年份 + 赛事 两个下拉；返回当前 scope id。改变时回调 onChange(scopeId)。 */
  function scopeBar(mount, onChange) {
    var S = window.KPL_SEASONS;
    var el = typeof mount === "string" ? document.querySelector(mount) : mount;
    if (!S || !el) return "all";
    var saved = localStorage.getItem(SCOPE_KEY) || "all";
    var savedYear = "all", savedLg = "";
    if (/^\d{4}$/.test(saved)) savedYear = saved;
    else if (/^\d{8,}$/.test(saved)) { savedYear = saved.slice(0, 4); savedLg = saved; }

    el.innerHTML =
      '<div class="scope-lab">' + icon("sliders", 15) + '<span>数据范围</span></div>' +
      '<label class="fld"><span>年份</span><select id="scopeYear"></select></label>' +
      '<label class="fld"><span>赛事</span><select id="scopeLeague"></select></label>' +
      '<span class="scope-meta mono" id="scopeMeta"></span>';

    var selY = el.querySelector("#scopeYear");
    var selL = el.querySelector("#scopeLeague");
    var meta = el.querySelector("#scopeMeta");

    selY.insertAdjacentHTML("beforeend", '<option value="all">全部年份</option>');
    (S.years || []).slice().sort().reverse().forEach(function (y) {
      selY.insertAdjacentHTML("beforeend",
        '<option value="' + y + '"' + (String(y) === savedYear ? " selected" : "") + ">" + y + " 年</option>");
    });

    function fillLeagues() {
      var y = selY.value;
      var lgs = (S.leagues || []).filter(function (l) { return y !== "all" && String(l.year) === String(y); });
      selL.innerHTML = '<option value="">该年全部赛事</option>' + lgs.map(function (l) {
        return '<option value="' + l.id + '"' + (l.id === savedLg ? " selected" : "") + ">" +
          esc(l.name) + "（" + l.matches + " 场）</option>";
      }).join("");
      selL.disabled = (y === "all");
    }

    function current() {
      if (selY.value === "all") return "all";
      return selL.value || selY.value;
    }

    function emit() {
      var id = current();
      try { localStorage.setItem(SCOPE_KEY, id); } catch (e) {}
      if (meta) meta.textContent = scopeMeta(id);
      if (onChange) onChange(id);
    }

    fillLeagues();
    selY.addEventListener("change", function () { savedLg = ""; fillLeagues(); emit(); });
    selL.addEventListener("change", emit);
    var initId = current();
    if (meta) meta.textContent = scopeMeta(initId);
    return initId;
  }

  return {
    data: D, details: DT,
    esc: esc, fmtInt: fmtInt, pct: pct, signed: signed, track: track,
    mnum: mnum, mpct: mpct, mnumText: mnumText, mfrac: mfrac, chartPalette: chartPalette,
    dateCN: dateCN, weekdayCN: weekdayCN, cnDate: cnDate, cnHM: cnHM,
    todayCN: todayCN, nowKeyCN: nowKeyCN, tierOf: tierOf, icon: icon,
    scheduleIndex: scheduleIndex, matchMeta: matchMeta, stageLabel: stageLabel, stageTags: stageTags,
    leagueRows: leagueRows, leagueInfo: leagueInfo, leagueStandings: leagueStandings,
    currentLeagueId: currentLeagueId, leagueShortName: leagueShortName,
    side: side, resultRow: resultRow, muBody: muBody,
    heroCard: heroCard, playerCard: playerCard, wrChart: wrChart,
    countdown: countdown, scopeBar: scopeBar, scopeOf: scopeOf, scopeName: scopeName,
    isLive: isLive, liveBadge: liveBadge, exportCSV: exportCSV, lineChart: lineChart,
    coverageMask: coverageMask, battleCoverageMask: battleCoverageMask, coverageBadges: coverageBadges,
    favBtn: favBtn, favList: favList, favHas: favHas, favToggle: favToggle, renderFavStrip: renderFavStrip,
    brief: brief,
    init: init, refresh: scan
  };
})();

/* KPL bundled local runtime guidance */
/* Local-only: a single start/stop action with automatic event and mode selection. */
(function () {
  'use strict';
  if (!/^(localhost|127\.0\.0\.1|\[?::1\]?)$/i.test(location.hostname)) return;
  function mount() {
    var main = document.querySelector('main');
    if (!main || document.getElementById('kplLocalRuntime')) return;
    var style = document.createElement('style');
    style.textContent = '#kplLocalRuntime{position:relative;z-index:2;margin-bottom:20px;padding:14px 18px;border:1px solid #386785;border-radius:12px;background:#102236;color:#eaf1fa;font-size:13px;line-height:1.6}#kplLocalRuntime .local-row{display:flex;align-items:center;justify-content:space-between;gap:16px}#kplLocalRuntime p{margin:3px 0;color:#bbccdf}#kplLocalRuntime button{flex-shrink:0;padding:8px 16px;border:1px solid #4d92b5;border-radius:8px;background:#204961;color:#eaf1fa;cursor:pointer;font:inherit}#kplLocalRuntime button:disabled{opacity:.5;cursor:wait}#kplLocalRuntime [data-local-error]{color:#ffbc92}#kplLocalRuntime pre{max-height:180px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#091522;padding:10px;border-radius:6px}#kplLocalRuntime summary{cursor:pointer;color:#8ed8ff}@media(max-width:420px){#kplLocalRuntime{padding:12px}#kplLocalRuntime .local-row{gap:10px}}';
    document.head.appendChild(style);
    var box = document.createElement('aside');
    box.id = 'kplLocalRuntime';
    box.setAttribute('aria-label', '本地运行状态');
    box.innerHTML = '<div class="local-row"><div><strong>本地实时服务</strong><p data-local-status role="status">正在连接…</p></div><button type="button" data-local-toggle disabled>一键启动</button></div><p data-local-updated></p><p data-local-error role="alert" hidden></p><details data-local-diagnostics hidden><summary>查看异常详情</summary><pre data-local-logs></pre></details>';
    main.prepend(box);
    var token = '', state = null, busy = false, connected = false, actionError = '';
    var button = box.querySelector('[data-local-toggle]');
    var status = box.querySelector('[data-local-status]');
    function active() {
      return state && Object.keys(state.processes).some(function (key) {return state.processes[key].running;});
    }
    function render() {
      var running = active();
      button.disabled = busy || !connected || !!(state && state.external_collector);
      button.textContent = busy ? '处理中…' : running ? '停止' : '一键启动';
      if (busy) return;
      if (!connected) status.textContent = '请双击“启动网站.bat”打开本地服务。';
      else if (state.external_collector) status.textContent = '已有采集服务运行中。';
      else if (state.running) {
        var labels = {waiting_start:'等待开赛',waiting_schedule:'等待比赛',waiting_battle:'等待对局',waiting_next_match:'等待下一场',day_complete:'今日比赛已结束',error:'采集异常'};
        var record = state.collector_record || {};
        status.textContent = state.mode === 'collect' ? '运行中 · 正在采集（暂无模型，未生成预测）' : '运行中 · 采集与预测已启动';
        if (state.record_from_current_run && labels[record.state]) status.textContent = labels[record.state] + (state.mode === 'collect' ? ' · 仅采集' : ' · 实时服务运行中');
      } else status.textContent = running ? '运行异常' : '未启动 · 点击即可自动跟随赛事';
      var warning = '';
      if (state && state.running && Date.now() - new Date(state.started_at).getTime() > 120000 && (!state.record_from_current_run || state.record_age_seconds > 120)) warning = '数据暂未更新，正在等待比赛或网络恢复。';
      var error = actionError || (state && state.error) || warning;
      var alert = box.querySelector('[data-local-error]');
      alert.textContent = error;
      alert.hidden = !error;
      var updated = state && state.record_from_current_run ? state.collector_record.updated_at : null;
      box.querySelector('[data-local-updated]').textContent = updated ? '最近采集：' + updated : '';
      var details = box.querySelector('[data-local-diagnostics]');
      details.hidden = !(error && state && Object.keys(state.logs).length);
      box.querySelector('[data-local-logs]').textContent = state ? Object.keys(state.logs).map(function (key) {return state.logs[key];}).join('\n') : '';
    }
    async function refresh() {
      if (busy) return;
      try {
        var response = await fetch('/__kpl_local__/status', {cache:'no-store',signal:AbortSignal.timeout(5000)});
        if (!response.ok) throw new Error('offline');
        state = await response.json();
        token = state.token;
        connected = true;
      } catch (e) {connected = false;}
      render();
    }
    button.addEventListener('click', async function () {
      if (busy || !connected) return;
      var action = active() ? 'stop' : 'start';
      busy = true;
      actionError = '';
      render();
      status.textContent = action === 'stop' ? '正在停止…' : '正在启动…';
      try {
        var response = await fetch('/__kpl_local__/' + action, {method:'POST',headers:{'Content-Type':'application/json','X-KPL-Token':token},body:'{}'});
        var result = await response.json();
        if (!response.ok) throw new Error(result.error || '启动未成功，请重试。');
        state = result;
      } catch (e) {actionError = e.message || '连接中断，请稍后重试。';}
      finally {busy = false; render();}
    });
    refresh();
    window.setInterval(function () {if (!document.hidden) refresh();}, 5000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
