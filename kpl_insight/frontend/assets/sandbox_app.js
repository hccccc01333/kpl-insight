/* 胜率沙盘 · 纯前端交互
   数据来自 assets/sandbox.js（build_sandbox_data.py 生成），不请求后端。 */
(function () {
  "use strict";
  var D = window.KPL_SANDBOX;
  var K = window.KPL;
  if (!D || !K) return;
  K.init();

  var $ = function (s) { return document.querySelector(s); };
  var state = {
    battle: D.defaultBattle || 0,
    frame: D.defaultFrame || 0,
    mode: "hist"
  };
  var wi = { gd: 0, kd: 0, td: 0, obj: 0 };
  var drag = { on: false };

  function esc(s) { return K.esc ? K.esc(s) : String(s == null ? "" : s); }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function pct(p, digits) {
    if (p == null || isNaN(p)) return "—";
    return (p * 100).toFixed(digits == null ? 1 : digits) + "%";
  }
  function num(v) {
    if (v == null || isNaN(v)) return "—";
    return Number(v).toLocaleString("zh-CN");
  }
  function signed(v) {
    if (v == null || isNaN(v)) return "—";
    return (v > 0 ? "+" : "") + Number(v).toLocaleString("zh-CN");
  }
  function signedPct(v, digits) {
    if (v == null || isNaN(v)) return "—";
    var pp = v * 100;
    if (Math.abs(pp) < 0.05) return "0.0 个百分点";
    return (pp > 0 ? "+" : "") + pp.toFixed(digits == null ? 1 : digits) + " 个百分点";
  }
  function teamOr(v, fallback) { return v || fallback; }
  function durText(b) {
    var d = Number(b.dur || 0);
    return d ? d.toFixed(1) + " 分钟" : "—";
  }

  /* ---------- 颜色 ---------- */
  function hexRgb(hex) {
    var n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function mix(a, b, t) {
    var A = hexRgb(a), B = hexRgb(b);
    var c = A.map(function (v, i) { return Math.round(v + (B[i] - v) * t); });
    return "rgb(" + c.join(",") + ")";
  }
  function pColor(p) {
    if (p == null || isNaN(p)) return "#F1F2F4";
    p = clamp(p, 0, 1);
    if (p < 0.5) return mix("#D5374B", "#F2F3F5", p / 0.5);
    return mix("#F2F3F5", "#0F8A78", (p - 0.5) / 0.5);
  }
  function pTextColor(p) {
    if (p == null || isNaN(p)) return "var(--muted)";
    return p >= 0.5 ? "var(--teal)" : "var(--red)";
  }

  /* ---------- 基础数据 ---------- */
  function battleAt(i) { return D.battles[i]; }
  function matchForBattle(bi) {
    var b = battleAt(bi);
    for (var i = 0; i < D.matches.length; i++) {
      if (D.matches[i].id === b.mid) return D.matches[i];
    }
    return null;
  }
  function stateOf(f) {
    return { m: f[0], gd: f[2], kd: f[3], td: f[4], obj: f[5] };
  }
  function maxFrameMinute() {
    var mx = 25;
    D.battles.forEach(function (b) {
      b.frames.forEach(function (f) { if (f[0] > mx) mx = f[0]; });
    });
    return Math.ceil(mx / 5) * 5;
  }
  function nearestFrameIndex(b, minute, requireP) {
    var best = 0, bestD = Infinity;
    for (var i = 0; i < b.frames.length; i++) {
      var f = b.frames[i];
      if (requireP && f[1] == null) continue;
      var d = Math.abs(f[0] - minute);
      if (d < bestD) { bestD = d; best = i; }
    }
    return best;
  }

  /* ---------- Wilson 区间 ---------- */
  function wilson(wins, n) {
    if (!n) return [null, null];
    var p = wins / n, z = 1.96;
    var denom = 1 + z * z / n;
    var center = (p + z * z / (2 * n)) / denom;
    var half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom;
    return [Math.max(0, center - half), Math.min(1, center + half)];
  }

  /* ---------- 同状态检索 ---------- */
  function findAnalogs(s, exclude) {
    var rows = [];
    for (var bi = 0; bi < D.battles.length; bi++) {
      if (bi === exclude) continue;
      var b = D.battles[bi];
      for (var fi = 0; fi < b.frames.length; fi++) {
        var f = b.frames[fi];
        if (f[1] == null) continue;
        var dm = Math.abs(f[0] - s.m) / 4;
        var dg = Math.abs(f[2] - s.gd) / 3000;
        var dk = Math.abs(f[3] - s.kd) / 3;
        var dt = Math.abs(f[4] - s.td) / 2.5;
        var dobj = Math.abs(f[5] - s.obj) / 6;
        var dist = dm * 1.1 + dg * 1.0 + dk * 0.45 + dt * 0.65 + dobj * 0.5;
        rows.push({ d: dist, bi: bi, fi: fi, b: b, f: f });
      }
    }
    rows.sort(function (a, b) { return a.d - b.d; });
    // 统计口径：一局只取最接近的一帧，n = 独立对局数。
    // 若按帧计数，同一局会在 n 里出现多次，Wilson 区间会被虚假地收窄。
    var top = [], seenBattle = {};
    for (var i = 0; i < rows.length && top.length < 40; i++) {
      var x = rows[i];
      if (seenBattle[x.bi]) continue;
      seenBattle[x.bi] = 1;
      top.push(x);
    }
    var n = top.length;
    var wins = 0;
    top.forEach(function (x) { if (x.b.win === 1) wins++; });
    var rate = n ? wins / n : null;
    var ci = wilson(wins, n);
    var examples = top.slice(0, 3);
    return {
      n: n, wins: wins, rate: rate, lo: ci[0], hi: ci[1],
      examples: examples,
      medianDist: n ? top[Math.floor(n / 2)].d : null
    };
  }

  /* ---------- 控件 ---------- */
  function renderMatches() {
    var sel = $("#sbMatch");
    if (!sel) return;
    sel.innerHTML = D.matches.map(function (m, i) {
      return '<option value="' + i + '">' + esc((m.date || "").slice(5)) + " " +
        esc(m.t1) + " vs " + esc(m.t2) + "</option>";
    }).join("");
    var cur = battleAt(state.battle).mid;
    for (var i = 0; i < D.matches.length; i++) {
      if (D.matches[i].id === cur) { sel.value = String(i); break; }
    }
  }
  function renderBattles() {
    var sel = $("#sbBattle");
    var m = matchForBattle(state.battle);
    if (!sel || !m) return;
    sel.innerHTML = m.battles.map(function (bi) {
      var b = battleAt(bi);
      return '<option value="' + bi + '">G' + b.seq + " · " + esc(b.t1) + " vs " +
        esc(b.t2) + "</option>";
    }).join("");
    sel.value = String(state.battle);
  }

  function loadBattle(bi, minute) {
    if (bi == null || !battleAt(bi)) return;
    state.battle = bi;
    var b = battleAt(bi);
    var target = minute == null ? b.frames[Math.floor(b.frames.length / 2)][0] : minute;
    state.frame = nearestFrameIndex(b, target, true);
    var slider = $("#sbMinute");
    if (slider) {
      slider.max = Math.max(0, b.frames.length - 1);
      slider.value = state.frame;
    }
    wi = { gd: 0, kd: 0, td: 0, obj: 0 };
    renderMatches();
    renderBattles();
    renderAll();
  }

  function setFrame(i) {
    var b = battleAt(state.battle);
    state.frame = clamp(i, 0, b.frames.length - 1);
    var slider = $("#sbMinute");
    if (slider) slider.value = state.frame;
    wi = { gd: 0, kd: 0, td: 0, obj: 0 };
    renderAll();
  }

  /* ---------- 概率地形 ---------- */
  function renderSurface() {
    var host = $("#sbSurface");
    var b = battleAt(state.battle);
    var f = b.frames[state.frame] || b.frames[0];
    if (!host) return;
    var W = Math.max(320, host.clientWidth || 720);
    var H = clamp(W * 0.5, 300, 430);
    var pad = { l: 58, r: 14, t: 16, b: 40 };
    var plotW = W - pad.l - pad.r;
    var plotH = H - pad.t - pad.b;
    var maxM = maxFrameMinute();
    var minG = D.surface.goldEdges[0];
    var maxG = D.surface.goldEdges[D.surface.goldEdges.length - 1];
    // 数值安全：避免 0 宽高
    plotW = Math.max(120, plotW);
    plotH = Math.max(150, plotH);

    function x(gd) { return pad.l + (gd - minG) / (maxG - minG) * plotW; }
    function y(m) { return pad.t + (1 - clamp(m, 0, maxM) / maxM) * plotH; }

    var svg = ['<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="胜率地图">'];
    svg.push('<rect x="0" y="0" width="' + W + '" height="' + H + '" fill="#FFFFFF"></rect>');

    // 网格单元
    D.surface.cells.forEach(function (c) {
      var x0 = x(D.surface.goldEdges[c.gi]);
      var x1 = x(D.surface.goldEdges[c.gi + 1]);
      var y0 = y(D.surface.minuteEdges[c.mi + 1]);
      var y1 = y(D.surface.minuteEdges[c.mi]);
      var p = state.mode === "hist" ? c.hist : c.model;
      var fill = p == null ? "#F1F2F4" : pColor(p);
      var op = c.n === 0 ? 0.32 : clamp(0.42 + c.n / 70 * 0.5, 0.42, 0.95);
      svg.push('<rect class="sb-cell" data-mi="' + c.mi + '" data-gi="' + c.gi +
        '" x="' + x0.toFixed(1) + '" y="' + y0.toFixed(1) + '" width="' +
        Math.max(0, x1 - x0).toFixed(1) + '" height="' +
        Math.max(0, y1 - y0).toFixed(1) + '" fill="' + fill +
        '" fill-opacity="' + op.toFixed(2) + '" stroke="#FFFFFF" stroke-width="1"></rect>');
    });

    // 0 金差参考线
    svg.push('<line x1="' + x(0) + '" y1="' + pad.t + '" x2="' + x(0) + '" y2="' +
      (pad.t + plotH) + '" stroke="#17191F" stroke-opacity=".18" stroke-dasharray="3 4"></line>');

    // 坐标轴
    [-20000, -10000, 0, 10000, 20000].forEach(function (g) {
      var label = g === 0 ? "0" : (g < 0 ? "−" : "+") + Math.abs(g / 10000) + "万";
      svg.push('<text x="' + x(g).toFixed(1) + '" y="' + (pad.t + plotH + 17) +
        '" text-anchor="middle" fill="#8A8F99" font-size="10" font-family="monospace">' +
        label + "</text>");
    });
    [0, 5, 10, 15, 20, 25].forEach(function (m) {
      if (m > maxM) return;
      svg.push('<text x="' + (pad.l - 8) + '" y="' + (y(m) + 3.5).toFixed(1) +
        '" text-anchor="end" fill="#8A8F99" font-size="10" font-family="monospace">' +
        m + "'</text>");
    });
    svg.push('<text x="' + (pad.l + plotW) + '" y="' + (pad.t + plotH + 33) +
      '" text-anchor="end" fill="#A3A7B0" font-size="10" font-family="monospace">经济差（左边 − 右边）</text>');
    svg.push('<text x="' + pad.l + '" y="' + (pad.t - 4) +
      '" fill="#A3A7B0" font-size="10" font-family="monospace">分钟</text>');

    // 轨迹 + 当前点
    var pts = [];
    for (var i = 0; i <= state.frame && i < b.frames.length; i++) {
      var pf = b.frames[i];
      pts.push([x(pf[2]), y(pf[0])]);
    }
    if (pts.length > 1) {
      svg.push('<polyline points="' + pts.map(function (p) {
        return p[0].toFixed(1) + "," + p[1].toFixed(1);
      }).join(" ") + '" fill="none" stroke="#17191F" stroke-opacity=".26" stroke-width="1.6"></polyline>');
    }
    var cx = x(f[2]), cy = y(f[0]);
    svg.push('<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) +
      '" r="8" fill="#FFFFFF" stroke="#17191F" stroke-width="2"></circle>');
    if (f[1] != null) {
      svg.push('<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) +
        '" r="4" fill="' + pColor(f[1]) + '" stroke="#FFFFFF" stroke-width="1"></circle>');
    }
    svg.push("</svg>");
    host.innerHTML = svg.join("");

    // 悬停提示
    var tip = $("#sbTip");
    host.querySelectorAll("rect.sb-cell").forEach(function (rect) {
      var mi = +rect.getAttribute("data-mi");
      var gi = +rect.getAttribute("data-gi");
      var cell = null;
      for (var j = 0; j < D.surface.cells.length; j++) {
        if (D.surface.cells[j].mi === mi && D.surface.cells[j].gi === gi) { cell = D.surface.cells[j]; break; }
      }
      if (!cell) return;
      rect.addEventListener("mousemove", function (evt) {
        if (!tip) return;
        var r = host.getBoundingClientRect();
        var content = "<b>第 " + esc(D.surface.minuteLabels[mi]) + " 分钟</b> · 经济差 " +
          esc(D.surface.goldLabels[gi]) + "<br>";
        if (!cell.n) {
          content += "没有可参考的历史时刻";
        } else if (state.mode === "hist") {
          content += "历史上类似局面：左边队伍赢 <b>" + pct(cell.hist) + "</b><br>" +
            "参考了 " + cell.n + " 局独立对局 · 大致范围 " + pct(cell.lo) + "–" + pct(cell.hi) + "<br>" +
            "模型平均判断：" + pct(cell.model);
        } else {
          content += "模型平均判断：左边队伍赢 <b>" + pct(cell.model) + "</b><br>" +
            "参考了 " + cell.n + " 局独立对局<br>" +
            "历史上类似局面：" + pct(cell.hist) + "（" + pct(cell.lo) + "–" + pct(cell.hi) + "）";
        }
        tip.innerHTML = content;
        tip.style.display = "block";
        var left = evt.clientX - r.left + 12;
        var top = evt.clientY - r.top + 12;
        tip.style.left = Math.min(left, Math.max(0, host.clientWidth - 270)) + "px";
        tip.style.top = Math.min(top, Math.max(0, host.clientHeight - 92)) + "px";
      });
      rect.addEventListener("mouseleave", function () { if (tip) tip.style.display = "none"; });
      rect.addEventListener("click", function () {
        var m0 = D.surface.minuteEdges[mi], m1 = D.surface.minuteEdges[mi + 1];
        var g0 = D.surface.goldEdges[gi], g1 = D.surface.goldEdges[gi + 1];
        var best = -1, bestD = Infinity;
        b.frames.forEach(function (pf, idx) {
          if (pf[1] == null) return;
          if (pf[0] < m0 || pf[0] >= m1 || pf[2] < g0 || pf[2] >= g1) return;
          var d = Math.abs(pf[0] - (m0 + m1) / 2) + Math.abs(pf[2] - (g0 + g1) / 2) / 1000;
          if (d < bestD) { bestD = d; best = idx; }
        });
        if (best >= 0) setFrame(best);
      });
    });
  }

  function renderLegend() {
    var el = $("#sbLegend");
    if (!el) return;
    var modeText = state.mode === "hist"
      ? "颜色越偏绿，左边队伍历史上赢得越多；越偏红，右边赢得多；颜色越淡，可参考的时刻越少"
      : "颜色越偏绿，模型越看好左边队伍；越偏红，越看好右边；颜色越淡，参考时刻越少";
    el.innerHTML = '<span>红：右边占优</span><span class="grad"></span><span>绿：左边占优</span>' +
      '<span><i class="dot"></i>你正在看的时刻</span><span>' + esc(modeText) + "</span>";
  }

  /* ---------- 胜率曲线 ---------- */
  function renderCurve() {
    var host = $("#sbCurve");
    var b = battleAt(state.battle);
    if (!host) return;
    var W = Math.max(320, host.clientWidth || 720);
    var H = 220;
    var pad = { l: 38, r: 14, t: 12, b: 26 };
    var plotW = W - pad.l - pad.r;
    var plotH = H - pad.t - pad.b;
    var maxM = Math.max(20, Math.ceil(maxFrameMinute() / 5) * 5);
    function x(m) { return pad.l + clamp(m, 0, maxM) / maxM * plotW; }
    function y(p) { return pad.t + (1 - clamp(p, 0, 1)) * plotH; }
    var svg = ['<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="模型每一分钟的判断">'];
    [0, 0.25, 0.5, 0.75, 1].forEach(function (p) {
      svg.push('<line x1="' + pad.l + '" y1="' + y(p) + '" x2="' + (pad.l + plotW) +
        '" y2="' + y(p) + '" stroke="' + (p === 0.5 ? "#A3A7B0" : "#E7E8EC") +
        '" stroke-width="' + (p === 0.5 ? "1" : "1") + '"' +
        (p === 0.5 ? ' stroke-dasharray="4 4"' : "") + "></line>");
      svg.push('<text x="' + (pad.l - 6) + '" y="' + (y(p) + 3.5) +
        '" text-anchor="end" fill="#8A8F99" font-size="10" font-family="monospace">' +
        Math.round(p * 100) + "%</text>");
    });
    [0, 5, 10, 15, 20, 25, 30].forEach(function (m) {
      if (m > maxM) return;
      svg.push('<text x="' + x(m) + '" y="' + (H - 6) +
        '" text-anchor="middle" fill="#8A8F99" font-size="10" font-family="monospace">' +
        m + "'</text>");
    });

    // 胜率曲线：遇到 null 就断线
    var d = "", started = false;
    b.frames.forEach(function (f) {
      if (f[1] == null) { started = false; return; }
      d += (started ? "L" : "M") + x(f[0]).toFixed(1) + "," + y(f[1]).toFixed(1);
      started = true;
    });
    if (d) {
      svg.push('<path d="' + d + '" fill="none" stroke="#1B1D24" stroke-width="2.4" ' +
        'stroke-linejoin="round" stroke-linecap="round"></path>');
    }

    // 事件刻度
    var evColor = {
      tower: "#2E6FD0", tyrant: "#0F8A78", dark_tyrant: "#6B5BD2",
      lord: "#F02F55", storm: "#C81E40", first_blood: "#D99200"
    };
    b.events.forEach(function (ev) {
      var ex = x(ev[0]);
      svg.push('<circle cx="' + ex.toFixed(1) + '" cy="' + (H - pad.b + 4) +
        '" r="2.6" fill="' + (evColor[ev[1]] || "#A3A7B0") + '"><title>' +
        esc(ev[2]) + "</title></circle>");
    });

    // 当前时间
    var f = b.frames[state.frame] || b.frames[0];
    svg.push('<line x1="' + x(f[0]) + '" y1="' + pad.t + '" x2="' + x(f[0]) + '" y2="' +
      (pad.t + plotH) + '" stroke="#F02F55" stroke-opacity=".55" stroke-dasharray="3 3"></line>');
    if (f[1] != null) {
      svg.push('<circle cx="' + x(f[0]) + '" cy="' + y(f[1]) + '" r="5" fill="' +
        pColor(f[1]) + '" stroke="#FFFFFF" stroke-width="2"></circle>');
    }
    svg.push('<rect class="sb-overlay" x="' + pad.l + '" y="' + pad.t + '" width="' + plotW +
      '" height="' + plotH + '" fill="transparent" style="cursor:crosshair"></rect>');
    svg.push("</svg>");
    host.innerHTML = svg.join("");

    var overlay = host.querySelector(".sb-overlay");
    if (!overlay) return;
    function pick(evt) {
      var r = overlay.getBoundingClientRect();
      var px = (evt.clientX - r.left) / Math.max(1, r.width) * W;
      var m = (px - pad.l) / Math.max(1, plotW) * maxM;
      setFrame(nearestFrameIndex(b, m, false));
    }
    overlay.addEventListener("pointerdown", function (evt) {
      drag.on = true;
      if (overlay.setPointerCapture) overlay.setPointerCapture(evt.pointerId);
      pick(evt);
    });
    overlay.addEventListener("pointermove", function (evt) {
      if (drag.on) pick(evt);
    });
    overlay.addEventListener("pointerup", function () { drag.on = false; });
    overlay.addEventListener("pointercancel", function () { drag.on = false; });
  }

  /* ---------- 一句话结论（普通观众入口） ---------- */
  function renderPlain(b, f, s, a) {
    var host = $("#sbPlain");
    if (!host) return;
    var p = f[1], pFrame = f, pFallback = false;
    if (p == null) {
      var fb = b.frames[nearestFrameIndex(b, f[0], true)];
      if (fb && fb[1] != null) {
        p = fb[1];
        pFrame = fb;
        pFallback = true;
      }
    }
    var t1 = teamOr(b.t1, "左边队伍");
    var t2 = teamOr(b.t2, "右边队伍");
    var winTeam = b.win === 1 ? t1 : b.win === 2 ? t2 : "未知";
    var gap = s.gd;
    var gapTxt = (gap == null || isNaN(gap)) ? "经济差暂缺" :
      (gap === 0 ? "双方经济基本持平" :
        (gap > 0 ? t1 + " 领先 " + Math.abs(gap) + " 金币" :
          t2 + " 领先 " + Math.abs(gap) + " 金币"));
    var fav = p == null ? null : (p >= 0.5 ? t1 : t2);
    var favP = p == null ? null : Math.max(p, 1 - p);
    var histFav = a.rate == null ? null : (a.rate >= 0.5 ? t1 : t2);
    var histWins = a.rate == null ? null : (a.rate >= 0.5 ? a.wins : a.n - a.wins);
    var histP = a.rate == null ? null : Math.max(a.rate, 1 - a.rate);
    var line2 = p == null ? "这一分钟模型没有有效判断。" :
      "模型认为 " + fav + " 更可能赢（" + pct(favP) + "）";
    if (a.rate != null) {
      line2 += "；历史上最像的 " + a.n + " 局里，" + histFav +
        " 最终赢了 " + histWins + " 次（" + pct(histP) + "）";
    }
    line2 += "。";
    host.innerHTML =
      '<div class="big">第 ' + f[0].toFixed(1) + " 分钟：" + esc(gapTxt) + "。</div>" +
      '<div class="sub">' + esc(line2) + "</div>" +
      (pFallback ? '<div class="hint">这一分钟没有模型数字，显示的是最近一次判断。</div>' : "") +
      '<div class="hint">这局最终：<b>' + esc(winTeam) + "</b> 赢了 · " + esc(b.date || "") + " · 第 " + b.seq + " 局。</div>" +
      '<div class="hint">这是“当前局面 + 历史同类”的参考，不是结果承诺。拖动时间条，看看模型什么时候改主意。</div>';
  }

  /* ---------- 状态卡 ---------- */
  function renderState(b, f, s, a) {
    var host = $("#sbState");
    if (!host) return;
    var pFrame = f, p = f[1], pFallback = false;
    if (p == null) {
      var fallback = b.frames[nearestFrameIndex(b, f[0], true)];
      if (fallback && fallback[1] != null) {
        pFrame = fallback;
        p = fallback[1];
        pFallback = true;
      }
    }
    var p2 = p == null ? null : 1 - p;
    var t1 = teamOr(b.t1, "阵营 1");
    var t2 = teamOr(b.t2, "阵营 2");
    var winTeam = b.win === 1 ? t1 : t2;
    var gap = (p != null && a.rate != null) ? p - a.rate : null;
    var lowCls = a.n < 10 ? " sb-low" : "";
    var matchLink = b.mid ? '<a class="sb-link" href="match.html?id=' +
      encodeURIComponent(b.mid) + "&g=" + b.seq + '">看这局的完整复盘 →</a>' : "";
    host.innerHTML =
      '<div class="panel-title">这一刻 <em>模型判断 · ' +
        (pFallback ? "最近一次在第 " + pFrame[0].toFixed(1) + " 分钟" :
          "第 " + f[0].toFixed(1) + " 分钟") + "</em></div>" +
      '<div class="sb-state-top">' +
        '<div><span class="sb-team">左边 · ' + esc(t1) + '</span><div class="p" style="color:' +
          pTextColor(p) + '">' + pct(p) + "</div></div>" +
        '<div class="sb-vs">VS</div>' +
        '<div class="right"><span class="sb-team">右边 · ' + esc(t2) + '</span><div class="p" style="color:' +
          pTextColor(p2) + '">' + pct(p2) + "</div></div>" +
      "</div>" +
      '<div class="sb-state-meta"><span class="sb-tag gold">第 ' + b.seq + " 局</span>" +
        "<span>" + esc(b.date) + "</span><span>最终赢家：" + esc(winTeam) + "</span>" +
        "<span>" + esc(durText(b)) + "</span>" +
        (b.src && b.src !== "v12" ? '<span class="sb-tag">这局没有当前模型重算</span>' : "") +
        (pFallback ? '<span class="sb-tag">这一分钟没有模型数字 · 显示最近一次判断</span>' : "") +
        "</div>" +
      '<div class="sb-stat-grid">' +
        '<div class="sb-stat"><div class="k">经济差（左边 − 右边）</div><div class="v ' +
          (s.gd > 0 ? "pos" : s.gd < 0 ? "neg" : "") + '">' + signed(s.gd) + "</div></div>" +
        '<div class="sb-stat"><div class="k">击杀差（左 − 右）</div><div class="v ' +
          (s.kd > 0 ? "pos" : s.kd < 0 ? "neg" : "") + '">' + signed(s.kd) + "</div></div>" +
        '<div class="sb-stat"><div class="k">推塔差（左 − 右）</div><div class="v ' +
          (s.td > 0 ? "pos" : s.td < 0 ? "neg" : "") + '">' + signed(s.td) + "</div></div>" +
        '<div class="sb-stat"><div class="k">龙/资源差（左 − 右）</div><div class="v ' +
          (s.obj > 0 ? "pos" : s.obj < 0 ? "neg" : "") + '">' + signed(s.obj) + "</div></div>" +
      "</div>" +
      '<div class="sb-hist">' +
        '<div class="sb-hist-top"><span class="k">历史上类似局面：左边赢的比例</span>' +
          '<span class="v">' + pct(a.rate) + "</span></div>" +
        '<div class="sb-hist-sub">大致范围 ' + pct(a.lo) + "–" + pct(a.hi) +
          " · 从 " + D.coverage.replayBattles + " 局里挑了 " + a.n + " 局最像的局面</div>" +
        '<div class="sb-hist-gap' + lowCls + '">' +
          (gap == null ? "参考时刻不足，暂不比较。" :
            "模型比历史" + (gap >= 0 ? "高" : "低") + " <b>" +
            Math.abs(gap * 100).toFixed(1) + " 个百分点</b>；" +
            (a.n < 10 ? "参考时刻偏少，百分比不稳定。" :
              "只能说明历史上类似局面怎样，不能说明是它导致了输赢。")) +
        "</div>" +
        '<div class="sb-state-meta" style="margin-top:9px">' + matchLink + "</div>" +
      "</div>";
  }

  /* ---------- What-if ---------- */
  function wiValue(k) {
    if (k === "gd") {
      var v = wi.gd / 1000;
      return (v > 0 ? "+" : "") + (Math.round(v * 100) / 100) + " 千";
    }
    return (wi[k] > 0 ? "+" : "") + wi[k];
  }
  function renderWhatIf(b, f, s, a) {
    var host = $("#sbWhatIf");
    if (!host) return;
    host.innerHTML =
      '<div class="panel-title">如果局面变一点 <em>拖动滑杆，看看历史胜率怎么变</em></div>' +
      '<div class="sb-whatif-grid">' +
        '<label class="sb-wi"><span class="lab">经济领先 <b id="wiGdV">' + wiValue("gd") +
          '</b></span><input id="wiGd" type="range" min="-5" max="5" step="0.25" value="' +
          (wi.gd / 1000) + '"></label>' +
        '<label class="sb-wi"><span class="lab">推塔 <b id="wiTdV">' + wiValue("td") +
          '</b></span><input id="wiTd" type="range" min="-5" max="5" step="1" value="' + wi.td + '"></label>' +
        '<label class="sb-wi"><span class="lab">击杀 <b id="wiKdV">' + wiValue("kd") +
          '</b></span><input id="wiKd" type="range" min="-10" max="10" step="1" value="' + wi.kd + '"></label>' +
        '<label class="sb-wi"><span class="lab">龙/资源 <b id="wiObjV">' + wiValue("obj") +
          '</b></span><input id="wiObj" type="range" min="-10" max="10" step="1" value="' + wi.obj + '"></label>' +
      "</div>" +
      '<div class="sb-whatif-out" id="wiOut">—</div>' +
      '<div class="sb-chips" id="wiChips"></div>' +
      '<div class="sb-whatif-foot"><span class="note">这是历史对比，不能说明“赢了是因为多拿了一条龙”；某个资源变多，历史上胜率不一定更高，可能只是样本波动。</span>' +
        '<button class="btn ghost sm" id="wiReset" type="button">恢复原样</button></div>';

    var bind = function (id, key, isGd) {
      var el = $("#" + id);
      if (!el) return;
      el.addEventListener("input", function () {
        wi[key] = isGd ? Math.round(parseFloat(el.value) * 1000) : parseInt(el.value, 10) || 0;
        var lab = $("#" + id + "V");
        if (lab) lab.textContent = wiValue(key);
        updateWhatIfOutput();
      });
    };
    bind("wiGd", "gd", true);
    bind("wiTd", "td", false);
    bind("wiKd", "kd", false);
    bind("wiObj", "obj", false);
    var reset = $("#wiReset");
    if (reset) {
      reset.addEventListener("click", function () {
        wi = { gd: 0, kd: 0, td: 0, obj: 0 };
        ["wiGd", "wiTd", "wiKd", "wiObj"].forEach(function (id) {
          var el = $("#" + id);
          if (el) el.value = 0;
        });
        ["gd", "kd", "td", "obj"].forEach(function (k) {
          var lab = $("#wi" + k.charAt(0).toUpperCase() + k.slice(1) + "V");
          if (lab) lab.textContent = wiValue(k);
        });
        updateWhatIfOutput();
      });
    }
    updateWhatIfOutput();
  }

  function updateWhatIfOutput() {
    var out = $("#wiOut");
    var chips = $("#wiChips");
    if (!out) return;
    var b = battleAt(state.battle);
    var f = b.frames[state.frame] || b.frames[0];
    var s = stateOf(f);
    var base = findAnalogs(s, state.battle);
    var adj = {
      m: s.m, gd: s.gd + wi.gd, kd: s.kd + wi.kd,
      td: s.td + wi.td, obj: s.obj + wi.obj
    };
    var after = findAnalogs(adj, state.battle);
    var delta = (base.rate != null && after.rate != null) ? after.rate - base.rate : null;
    out.innerHTML =
      '<div><span class="big">' + pct(base.rate) + " → " + pct(after.rate) + "</span>" +
      (delta == null ? "" : ' <span class="delta ' + (delta >= 0 ? "pos" : "neg") + '">' +
        signedPct(delta) + "</span>") + "</div>" +
      '<div style="margin-top:3px">参考了 ' + after.n + " 局最像的历史对局" +
        (after.n < 8 ? ' <span class="sb-low">（偏少，结果不稳定）</span>' : "") + "</div>";

    if (chips) {
      if (base.rate == null) {
        chips.innerHTML = "";
      } else {
        var items = [
          ["+1 千经济", s, "gd", 1000],
          ["+1 座塔", s, "td", 1],
          ["+1 个人头", s, "kd", 1],
          ["+1 条龙", s, "obj", 1]
        ];
        chips.innerHTML = items.map(function (it) {
          var x = { m: it[1].m, gd: it[1].gd, kd: it[1].kd, td: it[1].td, obj: it[1].obj };
          x[it[2]] += it[3];
          var aa = findAnalogs(x, state.battle);
          var d = aa.rate == null ? null : aa.rate - base.rate;
          return '<span class="sb-chip ' + (d == null ? "" : d >= 0 ? "pos" : "neg") +
            '" title="历史上类似局面的差异，可能受样本影响，不一定代表因果">' +
            esc(it[0]) + " ≈ " + (d == null ? "—" : signedPct(d)) + "</span>";
        }).join("");
      }
    }
  }

  /* ---------- 同状态历史列表 ---------- */
  function renderAnalog(b, f, s, a) {
    var host = $("#sbAnalog");
    if (!host) return;
    if (!a.n) {
      host.innerHTML = '<div class="panel-title">历史上类似的局面 <em>挑了 40 局最像的独立对局</em></div>' +
        '<div class="sb-empty">没有找到可比较的历史时刻。</div>';
      return;
    }
    var rows = a.examples.map(function (x) {
      var bb = x.b;
      var w = bb.win === 1 ? bb.t1 : bb.t2;
      return '<div class="sb-analog-row" data-bi="' + x.bi + '" data-m="' + x.f[0] + '" title="' +
        esc(bb.t1) + " vs " + esc(bb.t2) + " · 最终赢家：" + esc(w) + '">' +
        '<span class="d">' + esc((bb.date || "").slice(5)) + "</span>" +
        '<span class="vs">' + esc(bb.t1) + " vs " + esc(bb.t2) + " · 第 " + bb.seq + " 局</span>" +
        '<span class="r ' + (bb.win === 1 ? "win" : "") + '">' +
          (bb.win === 1 ? "左边赢" : "右边赢") + "</span></div>";
    }).join("");
    host.innerHTML =
      '<div class="panel-title">历史上类似的局面 <em>挑了 40 局最像的独立对局</em></div>' +
      '<div class="sb-analog-sum">从 ' + D.coverage.replayBattles + " 局里挑了 <b>" + a.n +
        "</b> 局最像的对局，左边队伍最后赢了 <b>" + a.wins + "</b> 次（<b>" + pct(a.rate) +
        "</b>）。<br>每局只取最接近的一帧，n 为独立对局数；点一行，可以跳到那局同一分钟。</div>" +
      '<div class="sb-analog-list">' + rows + "</div>";
    host.querySelectorAll(".sb-analog-row").forEach(function (row) {
      row.addEventListener("click", function () {
        var bi = +row.getAttribute("data-bi");
        var m = parseFloat(row.getAttribute("data-m"));
        loadBattle(bi, m);
      });
    });
  }

  /* ---------- 模型体检 ---------- */
  function renderMeta() {
    var m = D.model;
    $("#sbMetaFrames").textContent = num(D.coverage.replayFrames);
    var mb = $("#sbMetaBattles");
    if (mb) mb.textContent = D.coverage.replayBattles + " 局";
    $("#sbMetaUpdated").textContent = D.updatedAt || "—";
    var mv = $("#sbModelVer"), mn = $("#sbModelN");
    if (mv) mv.textContent = m.version || "—";
    if (mn) mn.textContent = (m.testN == null ? "—" : m.testN + " 局");
    var gb = $("#sbGlossaryBattles"), gbr = $("#sbGlossaryBrier");
    if (gb) gb.textContent = D.coverage.replayBattles + " 局";
    if (gbr) gbr.textContent = m.brier == null ? "—" : m.brier.toFixed(3);
    var pn = $("#sbPhaseN");
    if (pn) pn.textContent = m.testN + " 局考试";
    $("#sbKpiBrier").textContent = m.brier == null ? "—" : m.brier.toFixed(3);
    $("#sbKpiBrierS").textContent = "在 " + m.testN + " 局没见过的比赛上考试";
    $("#sbKpiAcc").textContent = pct(m.acc);
    $("#sbKpiAccS").textContent = "只看这 " + m.testN + " 局考试，不代表每场都准";
    $("#sbKpiCoverage").textContent = D.coverage.replayBattles + " 局";
    $("#sbKpiCoverageS").textContent = D.coverage.replayMatches + " 场 · " +
      num(D.coverage.replayFrames) + " 个可以对照的时刻";
    var earlyCb = (m.comeback || {}).early || {};
    $("#sbKpiWeak").textContent = pct(earlyCb.acc);
    $("#sbKpiWeakS").textContent = "前 8 分钟落后、最后翻盘 · 参考 " + (earlyCb.n || 0) + " 个时刻";
  }

  function renderHealth() {
    var m = D.model;
    $("#sbHealthNote").textContent = m.version + " · 用 " + m.testN + " 局没见过的比赛考试 · 训练于 " +
      (m.trainedAt || "—");
    var cbAll = (m.comeback || {}).all || {};
    var kpis = [
      ["预测误差（越小越好）", m.brier == null ? "—" : m.brier.toFixed(3),
        "在 " + m.testN + " 局没见过的比赛上考试"],
      ["概率偏差", m.ece == null ? "—" : pct(m.ece),
        "越小越好；0 表示说 70% 时真的赢 70%"],
      ["胜负猜对率", pct(m.acc), m.testN + " 局考试 · " + num(m.testFrames) + " 个时刻"],
      ["翻盘局猜对率", pct(cbAll.acc), "最难的翻盘局 · " + (cbAll.n || 0) + " 个时刻"]
    ];
    $("#sbHealthKpis").innerHTML = kpis.map(function (x) {
      return '<div class="sb-health-kpi"><div class="k">' + esc(x[0]) + '</div><div class="v">' +
        esc(x[1]) + '</div><div class="s">' + esc(x[2]) + "</div></div>";
    }).join("");

    var labels = { early: "前 8 分钟", mid: "9–15 分钟", late: "16 分钟后", all: "整局平均" };
    var order = ["early", "mid", "late", "all"];
    $("#sbPhases").innerHTML = order.filter(function (k) { return m.phases[k]; }).map(function (k) {
      var p = m.phases[k];
      return '<div class="sb-phase"><div class="k">' + labels[k] + '</div><div class="v">' +
        pct(p.acc) + '</div><div class="s">误差 ' + (p.brier == null ? "—" : p.brier.toFixed(3)) +
        ' · 偏差 ' + pct(p.ece) + ' · ' + p.n +
        ' 个时刻</div><div class="bar"><i style="width:' + clamp((p.acc || 0) * 100, 0, 100) +
        '%"></i></div></div>';
    }).join("");

    renderReliability();
    renderBrierStrip();
    renderWorst();
    var tech = (D.techNotes || []).slice();
    if (D.calibration && D.calibration.ece != null) {
      tech.push("直播档案 ECE " + D.calibration.ece.toFixed(3) + "（非独立 test，仅供观察校准形态）。");
    }
    var rvl = (D.model.live || {}).replayVsLive;
    if (rvl && rvl.gapAll != null) {
      tech.push("重放 vs 直播 ΔBrier " + Number(rvl.gapAll).toFixed(3) + "（同一批局，直播更差）。");
    }
    $("#sbNotes").innerHTML = "<h3>看这些数字前，先知道</h3><ul>" + (D.notes || []).map(function (n) {
      return "<li>" + esc(n) + "</li>";
    }).join("") + "</ul>" +
      '<details class="sb-tech"><summary>给数据同学：口径与算法</summary><ul>' +
      tech.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") +
      "</ul></details>";
  }

  function renderReliability() {
    var host = $("#sbReliability");
    if (!host) return;
    var bins = (D.calibration.bins || []).filter(function (b) { return b.n > 0; });
    if (!bins.length) {
      host.innerHTML = '<div class="sb-empty">暂无直播预测档案。</div>';
      return;
    }
    var W = Math.max(280, host.clientWidth || 400);
    var H = 250;
    var pad = { l: 38, r: 14, t: 14, b: 30 };
    var plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
    function x(p) { return pad.l + p * plotW; }
    function y(p) { return pad.t + (1 - p) * plotH; }
    var svg = ['<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="模型说多少，实际赢多少">'];
    [0, 0.25, 0.5, 0.75, 1].forEach(function (p) {
      svg.push('<line x1="' + x(p) + '" y1="' + pad.t + '" x2="' + x(p) + '" y2="' +
        (pad.t + plotH) + '" stroke="#ECEFF3" stroke-width="1"></line>');
      svg.push('<line x1="' + pad.l + '" y1="' + y(p) + '" x2="' + (pad.l + plotW) +
        '" y2="' + y(p) + '" stroke="#ECEFF3" stroke-width="1"></line>');
      svg.push('<text x="' + (pad.l - 6) + '" y="' + (y(p) + 3.5) +
        '" text-anchor="end" fill="#8A8F99" font-size="10" font-family="monospace">' +
        Math.round(p * 100) + "%</text>");
      svg.push('<text x="' + x(p) + '" y="' + (H - 7) +
        '" text-anchor="middle" fill="#8A8F99" font-size="10" font-family="monospace">' +
        Math.round(p * 100) + "%</text>");
    });
    svg.push('<line x1="' + x(0) + '" y1="' + y(0) + '" x2="' + x(1) + '" y2="' + y(1) +
      '" stroke="#17191F" stroke-opacity=".38" stroke-dasharray="4 4"></line>');
    bins.forEach(function (b) {
      var r = 3 + Math.sqrt(b.n) / 3.2;
      svg.push('<circle cx="' + x(b.meanP).toFixed(1) + '" cy="' + y(b.obs).toFixed(1) +
        '" r="' + r.toFixed(1) + '" fill="#2E6FD0" fill-opacity=".55" stroke="#FFFFFF" stroke-width="1.2">' +
        "<title>模型说 " + pct(b.meanP) + " → 实际赢 " + pct(b.obs) +
        " · 参考 " + b.n + " 个时刻</title></circle>");
    });
    svg.push('<text x="' + (pad.l + plotW) + '" y="' + (H - 17) +
      '" text-anchor="end" fill="#A3A7B0" font-size="10" font-family="monospace">模型说的胜率</text>');
    svg.push("</svg>");
    host.innerHTML = svg.join("");
    var c = D.calibration;
    var live = D.model.live || {};
    var cps = (live.checkpoints || []).map(function (x) {
      return "第 " + x.m + " 分钟 " + pct(x.acc);
    });
    var note = "这是 " + c.nBattles + " 局直播时留下的记录，不是考试卷。";
    if (cps.length) note += cps.join("，") + "。";
    note += "同一局前后几分钟很像，只能看大致趋势。点越靠近斜线，说明模型说的概率越可信；点越大，参考时刻越多。";
    $("#sbRelNote").textContent = note;
  }

  function renderBrierStrip() {
    var host = $("#sbBrierStrip");
    if (!host) return;
    var rows = (D.model.holdout || []).slice().sort(function (a, b) {
      return (b.brier || 0) - (a.brier || 0);
    });
    if (!rows.length) {
      host.innerHTML = '<div class="sb-empty">暂无考试明细。</div>';
      return;
    }
    var maxB = Math.max(0.2, Math.max.apply(null, rows.map(function (r) { return r.brier || 0; })));
    host.innerHTML = rows.map(function (r) {
      var tag = r.isComeback ? "翻盘局" : "普通局";
      var date = (r.date || "").slice(5) || "—";
      return '<div class="sb-brier-row ' + (r.isComeback ? "cb" : "") + '" title="' +
        esc(r.t1 || r.id) + " vs " + esc(r.t2 || "—") + " · " + tag + ' · ' +
        (r.nPoints || 0) + ' 个时刻">' +
        '<span class="d">' + esc(date) + " · 第" + (r.seq || "?") + "局</span>" +
        '<span class="bar"><i style="width:' + clamp((r.brier || 0) / maxB * 100, 0, 100) +
        '%"></i></span><span class="v">' + (r.brier == null ? "—" : r.brier.toFixed(3)) +
        "</span></div>";
    }).join("") + '<div class="sb-rel-note">红色是翻盘局（' + rows.length + " 局里有 " +
      rows.filter(function (r) { return r.isComeback; }).length + " 局）。" +
      "条越短，这一局整体猜得越准；每局时刻数不同，不要只按单局排名。</div>";
  }

  function renderWorst() {
    var host = $("#sbWorst");
    if (!host) return;
    var rows = D.model.worst || [];
    var html = '<div class="sb-worst-row sb-worst-head"><div>比赛</div><div class="n">误差</div>' +
      '<div class="n">猜对率</div><div class="ty">类型</div></div>';
    rows.forEach(function (r) {
      var name = r.t1 ? esc(r.t1) + " vs " + esc(r.t2) : esc(r.id);
      var link = r.mid ? '<a class="sb-link" href="match.html?id=' + encodeURIComponent(r.mid) +
        "&g=" + r.seq + '">' + name + "</a>" : name;
      html += '<div class="sb-worst-row"><div class="vs">' + link +
        "<small>" + esc(r.date || "—") + " · 第" + (r.seq || "?") + "局</small></div>" +
        '<div class="n bad">' + (r.brier == null ? "—" : r.brier.toFixed(3)) + "</div>" +
        '<div class="n">' + pct(r.acc) + "</div><div class=\"ty\">" +
        (r.isComeback ? "翻盘局" : "普通局") + "</div></div>";
    });
    var bad = D.model.badBattle;
    if (bad) {
      var name2 = bad.t1 ? esc(bad.t1) + " vs " + esc(bad.t2) : esc(bad.id);
      html += '<div class="sb-worst-row"><div class="vs">' + name2 +
        "<small>特殊保护 · 触发 " + (bad.goldGuardHits || 0) + " 次</small></div>" +
        '<div class="n">' + (bad.brier == null ? "—" : bad.brier.toFixed(3)) + "</div>" +
        '<div class="n">' + pct(bad.acc) + "</div><div class=\"ty\">特殊保护</div></div>";
    }
    host.innerHTML = html;
  }

  /* ---------- 示例入口：找一场翻盘 / 碾压 ---------- */
  function pickComeback() {
    var best = null;
    D.battles.forEach(function (b, bi) {
      if (b.win !== 1 && b.win !== 2) return;
      var minLead = Infinity, minute = null;
      b.frames.forEach(function (f) {
        if (f[1] == null || f[2] == null) return;
        var lead = b.win === 1 ? f[2] : -f[2];
        if (lead < minLead) { minLead = lead; minute = f[0]; }
      });
      if (minute != null && minLead < -4000 && (!best || minLead < best.minLead)) {
        best = { bi: bi, minute: minute, minLead: minLead };
      }
    });
    return best;
  }

  function pickBlowout() {
    var best = null;
    D.battles.forEach(function (b, bi) {
      if (b.win !== 1 && b.win !== 2) return;
      var maxLead = -Infinity, minute = null;
      b.frames.forEach(function (f) {
        if (f[1] == null || f[2] == null) return;
        var lead = b.win === 1 ? f[2] : -f[2];
        if (lead > maxLead) { maxLead = lead; minute = f[0]; }
      });
      if (minute != null && maxLead > 8000 && (!best || maxLead > best.maxLead)) {
        best = { bi: bi, minute: minute, maxLead: maxLead };
      }
    });
    return best;
  }

  /* ---------- 事件绑定 ---------- */
  function bindControls() {
    var matchSel = $("#sbMatch");
    if (matchSel) {
      matchSel.addEventListener("change", function () {
        var m = D.matches[+matchSel.value];
        if (m && m.battles.length) loadBattle(m.battles[0], null);
      });
    }
    var battleSel = $("#sbBattle");
    if (battleSel) {
      battleSel.addEventListener("change", function () {
        loadBattle(+battleSel.value, null);
      });
    }
    var slider = $("#sbMinute");
    if (slider) {
      slider.addEventListener("input", function () { setFrame(+slider.value); });
    }
    document.querySelectorAll("#sbMode button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll("#sbMode button").forEach(function (b) { b.classList.remove("on"); });
        btn.classList.add("on");
        state.mode = btn.getAttribute("data-mode") || "hist";
        renderSurface();
        renderLegend();
      });
    });
    var rnd = $("#sbRandom");
    if (rnd) {
      rnd.addEventListener("click", function () {
        var bi = Math.floor(Math.random() * D.battles.length);
        var b = D.battles[bi];
        var valid = [];
        b.frames.forEach(function (f, i) { if (f[1] != null) valid.push(i); });
        var fi = valid.length ? valid[Math.floor(Math.random() * valid.length)] : 0;
        state.battle = bi;
        state.frame = fi;
        wi = { gd: 0, kd: 0, td: 0, obj: 0 };
        renderMatches();
        renderBattles();
        var sl = $("#sbMinute");
        if (sl) { sl.max = Math.max(0, b.frames.length - 1); sl.value = fi; }
        renderAll();
      });
    }
    var cb = $("#sbComeback");
    if (cb) {
      cb.addEventListener("click", function () {
        var x = pickComeback();
        if (x) loadBattle(x.bi, x.minute);
      });
    }
    var bl = $("#sbBlowout");
    if (bl) {
      bl.addEventListener("click", function () {
        var x = pickBlowout();
        if (x) loadBattle(x.bi, x.minute);
      });
    }
  }

  function renderAll() {
    var b = battleAt(state.battle);
    if (!b) return;
    if (state.frame >= b.frames.length) state.frame = b.frames.length - 1;
    var f = b.frames[state.frame] || b.frames[0];
    var s = stateOf(f);
    var a = findAnalogs(s, state.battle);
    var label = $("#sbMinuteLabel");
    if (label) label.textContent = f[0].toFixed(1) + "'";
    var meta = $("#sbCurveMeta");
    if (meta) meta.textContent = b.date + " · G" + b.seq + " · " + b.t1 + " vs " + b.t2;
    renderSurface();
    renderLegend();
    renderCurve();
    renderState(b, f, s, a);
    renderPlain(b, f, s, a);
    renderWhatIf(b, f, s, a);
    renderAnalog(b, f, s, a);
  }

  function applyDeepLink() {
    var qs;
    try { qs = new URLSearchParams(location.search); } catch (e) { return; }
    var bid = qs.get("battle");
    if (!bid) return;
    var m = parseFloat(qs.get("m"));
    var bi = -1;
    for (var i = 0; i < D.battles.length; i++) {
      if (D.battles[i].id === bid) { bi = i; break; }
    }
    var note = $("#sbJumpNote");
    if (!note) return;
    if (bi < 0) {
      note.textContent = "复盘链接里的这局不在沙盘覆盖的 " + D.coverage.replayBattles +
        " 局内；已载入默认对局。";
    } else {
      state.battle = bi;
      var b = D.battles[bi];
      state.frame = isFinite(m) ? nearestFrameIndex(b, m, false) : 0;
      note.textContent = "从复盘跳转：第 " + b.seq + " 局 · 第 " +
        b.frames[state.frame][0].toFixed(1) + " 分钟。下面就是这一刻的历史类似局面。";
    }
    note.hidden = false;
  }

  function init() {
    applyDeepLink();
    renderMatches();
    renderBattles();
    var slider = $("#sbMinute");
    var b = battleAt(state.battle);
    if (slider) {
      slider.max = Math.max(0, b.frames.length - 1);
      slider.value = state.frame;
    }
    bindControls();
    renderMeta();
    renderAll();
    renderHealth();
  }

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      renderSurface();
      renderCurve();
      renderReliability();
    }, 160);
  });

  init();
})();
