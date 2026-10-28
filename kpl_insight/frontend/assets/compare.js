var CP = (window.KPL && KPL.chartPalette) ? KPL.chartPalette() : {grid:'#E3E5EA',axis:'#D9DCE2',label:'#6E7480',line:'#2E6FD0',mark:'#F02F55',onLine:'#191B23'};
/* 峡谷有数 · 对比引擎（V5 阶段四「对比工具拆分」）
   ------------------------------------------------------------------
   原 compare.html 的三模式内联脚本抽成公共引擎，并新增「位置」模式。
   每个对比入口页各自 init 一个模式（一次加载只跑一个）：
     compare.html        → hero   英雄对比
     compare-team.html   → team   战队对比
     compare-player.html → player 选手对比
     compare-lane.html   → lane   位置（分路）对比
   赛段之间的变化沿用 stage.html（不在此引擎内）。

   约定：页面不自己调 KPL.init()，由 KPL_COMPARE.init() 统一初始化顶栏/页脚/范围条。
   用法：<script src="assets/compare.js?v=52"></script> 后 KPL_COMPARE.init("hero");
   URL 可分享：?items=对象A,对象B / ?trend=1（仅英雄、战队支持趋势）
*/
window.KPL_COMPARE = (function () {
  "use strict";

  var COLORS = [CP.mark, CP.line, "#8A6A3B", "#0F8A78"];
  var MAX = 4;
  var LANES = ["对抗路", "打野", "中路", "发育路", "游走"];
  var TRENDABLE = { hero: 1, team: 1 };   // 只有英雄 / 战队有逐年 by 数据，选手 / 位置无趋势

  var K, $, baseMode, trendView, mode, curScope, picked, posFilter = "all", posNorm = "pos", booted = false;

  /* ---------- 位置（分路）聚合 ----------
     把当前数据范围里的选手，按「实际出场位置」聚成 5 条分路画像；
     每条指标按选手出场局数加权（等价于"该分路全部局"的合计口径）。
     位置未知的选手不计入任何分路。 */
  function laneAgg(d) {
    var out = [];
    LANES.forEach(function (ln) {
      var ps = (d.players || []).filter(function (p) { return p.pos === ln; });
      var g = ps.reduce(function (a, p) { return a + (p.games || 0); }, 0);
      if (!g) return;
      function wavg(f) {
        // 缺失值不参与加权：只累计「该指标有有效样本」的选手局数作为分母，
        // 绝不用 (f(p) || 0) 把「没有数据」当成 0 混进平均值。
        var sum = 0, w = 0;
        ps.forEach(function (p) {
          var v = K.mnum(f(p)), gg = p.games || 0;
          if (v === null || !gg) return;
          sum += v * gg; w += gg;
        });
        return w ? sum / w : null;
      }
      var mV = 0, mW = 0;
      ps.forEach(function (p) {
        var mv = K.mnum(p.mvp), gg = p.games || 0;
        if (mv === null || !gg) return;
        mV += mv; mW += gg;
      });
      out.push({
        name: ln, lane: ln, games: g, n: ps.length,
        wr: wavg(function (p) { return p.wr; }),
        kda: wavg(function (p) { return p.kda; }),
        part: wavg(function (p) { return p.part; }),
        dmg: wavg(function (p) { return p.dmg; }),
        mvpRate: mW ? mV / mW * 100 : null
      });
    });
    return out;
  }

  /* ---------- 每种模式：数据源 / 名称 / 图标 / 维度 ---------- */
  var MODES = {
    hero: {
      list: function (d) {
        return (d.heroes || []).filter(function (x) { return x.games > 0; })
          .slice().sort(function (a, b) { return b.games - a.games; });
      },
      universe: function (d) { return (d.heroes || []).filter(function (x) { return x.games > 0; }); },
      name: function (x) { return x.name; },
      icon: function (x) { return x.icon; },
      target: "hero.html?id=",
      dims: [
        { label: "胜率", get: function (x) { return x.wr * 100; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "选用率", get: function (x, d) { return x.games / Math.max(1, d.totals.battles) * 100; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "禁用率", get: function (x, d) { return x.bans / Math.max(1, d.totals.battles) * 100; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "输出伤害", get: function (x) { return x.dmg; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "承伤", get: function (x) { return x.bh; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "KDA", get: function (x) { return x.kda; }, fmt: function (v) { return K.mnumText(v, 2); } }
      ]
    },
    player: {
      list: function (d) {
        return (d.players || []).filter(function (p) { return p.games >= 8; })
          .slice().sort(function (a, b) { return b.games - a.games; });
      },
      universe: function (d) { return (d.players || []).filter(function (p) { return p.games >= 8; }); },
      name: function (x) { return x.name; },
      icon: function (x) { return x.icon; },
      target: "players.html?q=",
      dims: [
        { label: "KDA", get: function (x) { return x.kda; }, fmt: function (v) { return K.mnumText(v, 2); } },
        { label: "胜率", get: function (x) { return x.wr * 100; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "MVP 率", get: function (x) { return x.mvp / Math.max(1, x.games) * 100; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "参团率", get: function (x) { return x.part; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "输出伤害", get: function (x) { return x.dmg; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "出场局数", get: function (x) { return x.games; }, weight: function () { return 1; }, fmt: function (v) { return K.mnumText(v, 0); } }
      ]
    },
    team: {
      list: function (d) {
        return (d.teams || []).filter(function (t) { return t.matches >= 10; })
          .slice().sort(function (a, b) { return b.wr - a.wr; });
      },
      universe: function (d) { return (d.teams || []).filter(function (t) { return t.matches >= 10; }); },
      name: function (x) { return x.team; },
      icon: function (x) { return x.icon; },
      target: "teams.html",
      dims: [
        { label: "单局胜率", get: function (x) { return x.wr * 100; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "大场胜率", get: function (x) { return x.mWin / Math.max(1, x.matches) * 100; }, weight: function (x) { return x.matches || 0; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "场均金差", get: function (x) { return x.goldDiff; }, fmt: function (v) { var n = K.mnum(v); return n === null ? "—" : (n > 0 ? "+" : "") + Math.round(n); } },
        { label: "场均击杀差", get: function (x) { return x.killDiff; }, fmt: function (v) { var n = K.mnum(v); return n === null ? "—" : (n > 0 ? "+" : "") + n.toFixed(1); } },
        { label: "出场局数", get: function (x) { return x.games; }, weight: function () { return 1; }, fmt: function (v) { return K.mnumText(v, 0); } }
      ]
    },
    lane: {
      list: function (d) { return laneAgg(d); },
      universe: function (d) { return laneAgg(d); },
      name: function (x) { return x.name; },
      icon: function () { return ""; },
      target: null,
      dims: [
        { label: "KDA", get: function (x) { return x.kda; }, fmt: function (v) { return K.mnumText(v, 2); } },
        { label: "胜率", get: function (x) { return x.wr * 100; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "MVP 率", get: function (x) { return x.mvpRate; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "参团率", get: function (x) { return x.part; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "输出伤害", get: function (x) { return x.dmg; }, fmt: function (v) { return K.mpct(v, 1); } },
        { label: "出场局数", get: function (x) { return x.games; }, weight: function () { return 1; }, fmt: function (v) { return K.mnumText(v, 0); } }
      ]
    }
  };

  /* 趋势模式（英雄 / 战队逐年胜率、禁用率） */
  var TREND = {
    "trend-team": {
      list: function (d) {
        return (d.teams || []).filter(function (t) { return t.by && t.by.length >= 3; })
          .slice().sort(function (a, b) { return b.wr - a.wr; });
      },
      name: function (x) { return x.team; },
      icon: function (x) { return x.icon; }
    },
    "trend-hero": {
      list: function (d) {
        return (d.heroes || []).filter(function (h) { return h.by && h.by.length >= 3; });
      },
      name: function (x) { return x.name; },
      icon: function (x) { return x.icon; }
    }
  };

  function conf() { return TREND[mode] || MODES[mode]; }
  function byPos(rows) {
    if (baseMode !== "player" || posFilter === "all") return rows;
    return rows.filter(function (x) { return x.pos === posFilter; });
  }
  function samePosMode() { return baseMode === "player" && posNorm === "pos"; }
  function currentList() { return byPos(conf().list(K.scopeOf(curScope))); }
  function currentUniverse() {
    var c = conf();
    return byPos(c.universe ? c.universe(K.scopeOf(curScope)) : conf().list(K.scopeOf(curScope)));
  }
  function pctRank(v, sorted) {
    if (!sorted.length) return null;
    if (sorted.length === 1) return 50;
    var below = 0;
    for (var i = 0; i < sorted.length; i++) { if (sorted[i] < v) below++; else break; }
    return below / (sorted.length - 1) * 100;
  }
  function curName(x) { return conf().name(x); }
  function curIcon(x) { return conf().icon(x); }

  /* 内部 mode 字符串：基础模式 +（支持趋势时）trend- 前缀 */
  function effMode() {
    if (!trendView || !TRENDABLE[baseMode]) return baseMode;
    return "trend-" + baseMode;
  }
  function syncMode() {
    mode = effMode();
    var tv = document.getElementById("trendToggle");
    if (tv) tv.checked = !!(trendView && TRENDABLE[baseMode]);
    var mw = document.getElementById("metricWrap");
    if (mw) mw.style.display = TREND[mode] ? "" : "none";
    var tw = document.getElementById("trendWrap");
    if (tw) tw.style.display = TRENDABLE[baseMode] ? "" : "none";
  }

  function populatePickers() {
    var list = currentList();
    var defaults = list.slice(0, 3).map(function (x) { return curName(x); });
    $("#pickers").innerHTML = [0, 1, 2, 3].map(function (i) {
      var opts = '<option value="">— 不参与 —</option>' + list.map(function (x) {
        return '<option>' + K.esc(curName(x)) + "</option>";
      }).join("");
      return '<label class="fld"><span>对象 ' + (i + 1) + '</span><select id="sel' + i + '">' + opts + "</select></label>";
    }).join("");
    [0, 1, 2, 3].forEach(function (i) {
      var sel = $("#sel" + i);
      var want = picked[i] || (i < 3 ? defaults[i] || "" : "");
      if ([].slice.call(sel.options).some(function (o) { return o.value === want; })) sel.value = want;
      sel.addEventListener("change", function () {
        picked = [0, 1, 2, 3].map(function (j) { return $("#sel" + j).value; });
        render();
      });
    });
    picked = [0, 1, 2, 3].map(function (j) { return $("#sel" + j).value; });
  }

  function trendMetricIdx() {
    var sel = document.getElementById("trendMetric");
    return (sel && sel.value === "ban") ? 3 : 2;
  }

  function emptyTip(txt) {
    $("#radar").innerHTML = '<div class="empty-tip" style="padding:80px 20px">' + txt + "</div>";
    $("#legend").innerHTML = "";
    $("#cmpTable").innerHTML = "";
    $("#cmpTip").textContent = "";
    clearInsights();
  }

  function clearInsights() {
    var box = document.getElementById("cmpInsights");
    if (box) box.innerHTML = "";
  }

  /* 相对范围均值的优势 / 短板摘要：用分位差，跨指标可读 */
  function renderInsights(series, dims, samePos) {
    var table = document.getElementById("cmpTable");
    if (!table || !table.parentNode) return;
    var box = document.getElementById("cmpInsights");
    if (!box) {
      box = document.createElement("div");
      box.id = "cmpInsights";
      box.className = "cmp-insights";
      table.parentNode.insertBefore(box, table.nextSibling);
    }
    function chip(kind, label, delta) {
      var n = Math.round(delta);
      return '<span class="cmp-chip ' + kind + '" title="相对范围均值的分位差">' +
        (kind === "up" ? "↑" : "↓") + " " + K.esc(label) + " " + (n > 0 ? "+" : "") + n + " 分位</span>";
    }
    box.innerHTML = series.map(function (se, ci) {
      var rows = dims.map(function (dim) {
        return {
          label: dim.label,
          delta: dim.values[ci].score - (samePos ? 50 : dim.avgScore),
          ok: dim.values[ci].raw !== null && (samePos || dim.avgRaw !== null)
        };
      }).filter(function (x) { return x.ok && x.label !== "出场局数"; });
      var up = rows.filter(function (x) { return x.delta > 0; })
        .sort(function (a, b) { return b.delta - a.delta; }).slice(0, 2);
      var down = rows.filter(function (x) { return x.delta < 0; })
        .sort(function (a, b) { return a.delta - b.delta; }).slice(0, 2);
      var chips = up.map(function (x) { return chip("up", x.label, x.delta); }).join("") +
        down.map(function (x) { return chip("down", x.label, x.delta); }).join("");
      if (!chips) chips = '<span class="cmp-chip neutral">各项接近范围均值</span>';
      return '<div class="cmp-insight"><b>' + K.esc(se.name) + "</b>" + chips + "</div>";
    }).join("");
  }

  /* ---------- 趋势折线视图 ---------- */
  function renderTrend(chosen) {
    if (chosen.length < 1) { emptyTip("请至少选择 1 个对象"); return; }
    clearInsights();
    var years = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026];
    var n = years.length;
    var W = 640, H = 470, PL = 46, PR = 16, PT = 26, PB = 40;
    var mi = trendMetricIdx();
    var vals = [];
    chosen.forEach(function (o) { (o.by || []).forEach(function (b) { if (b[mi] != null) vals.push(b[mi] * 100); }); });
    var lo = Math.max(0, Math.min.apply(null, vals.length ? vals : [40]) - 6);
    var hi = Math.min(100, Math.max.apply(null, vals.length ? vals : [60]) + 6);
    if (hi - lo < 20) { var mid = (hi + lo) / 2; lo = Math.max(0, mid - 12); hi = Math.min(100, mid + 12); }
    var X = function (y) { return PL + (y - 2019) / (n - 1) * (W - PL - PR); };
    var Y = function (p) { return PT + (1 - (p - lo) / (hi - lo)) * (H - PT - PB); };
    var svg = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="赛季趋势对比">';
    [lo, (lo + hi) / 2, hi].forEach(function (g) {
      svg += '<line x1="' + PL + '" y1="' + Y(g).toFixed(1) + '" x2="' + (W - PR) + '" y2="' + Y(g).toFixed(1) +
        '" stroke=' + CP.grid + ' stroke-dasharray="' + (Math.abs(g - (lo + hi) / 2) < 0.01 ? "0" : "4 6") + '"/>' +
        '<text x="' + (PL - 8) + '" y="' + (Y(g) + 4).toFixed(1) + '" text-anchor="end" font-size="10.5" fill=' + CP.label + ' font-family="Inter,monospace">' + Math.round(g) + "%</text>";
    });
    years.forEach(function (y) {
      svg += '<text x="' + X(y).toFixed(1) + '" y="' + (H - 14) + '" text-anchor="middle" font-size="11" fill=' + CP.label + ' font-family="Inter,monospace">' + y + "</text>";
    });
    chosen.forEach(function (o, ci) {
      var color = COLORS[ci % COLORS.length];
      var by = {};
      (o.by || []).forEach(function (b) { by[b[0]] = b[mi]; });
      var pts = [], dots = "";
      years.forEach(function (y) {
        if (by[y] != null) {
          var x = X(y).toFixed(1), yy = Y(by[y] * 100).toFixed(1);
          pts.push(x + "," + yy);
          dots += '<circle cx="' + x + '" cy="' + yy + '" r="3.4" fill="' + color + '"></circle>' +
            '<text x="' + x + '" y="' + (parseFloat(yy) - 9).toFixed(1) + '" text-anchor="middle" font-size="10" fill="' + color + '" font-family="Inter,monospace">' + Math.round(by[y] * 100) + "%</text>";
        }
      });
      svg += '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + color + '" stroke-width="2.2" stroke-linejoin="round"/>' + dots;
    });
    svg += "</svg>";
    $("#radar").innerHTML = svg;
    $("#legend").innerHTML = chosen.map(function (o, ci) {
      var ic = curIcon(o);
      return "<span><i style='background:" + COLORS[ci % COLORS.length] + "'></i>" +
        (ic ? '<img src="' + K.esc(ic) + '" alt="" style="width:20px;height:20px;border-radius:50%;object-fit:cover">' : "") +
        K.esc(curName(o)) + "</span>";
    }).join("");
    var head = "<thead><tr><th>年份</th>" + chosen.map(function (o) {
      var ic = curIcon(o);
      return '<th><span class="cmp-head">' + (ic ? '<img src="' + K.esc(ic) + '" alt="">' : "") + K.esc(curName(o)) + "</span></th>";
    }).join("") + "</tr></thead>";
    var body = "<tbody>" + years.filter(function (y) {
      return chosen.some(function (o) { return (o.by || []).some(function (b) { return b[0] === y; }); });
    }).map(function (y) {
      return "<tr><td>" + y + "</td>" + chosen.map(function (o) {
        var row = (o.by || []).filter(function (b) { return b[0] === y; })[0];
        return row && row[mi] != null ? "<td><b>" + Math.round(row[mi] * 100) + '%</b> <small style="color:var(--muted)">(' + row[1] + " 局)</small></td>"
                   : '<td><span style="color:var(--muted)">—</span></td>';
      }).join("") + "</tr>";
    }).join("") + "</tbody>";
    $("#cmpTable").innerHTML = head + body;
    $("#cmpTip").textContent = "折线为该对象逐年的" + (mi === 3 ? "禁用率" : "胜率") +
      "变化（括号内为当年局数）；空白年份表示当年出场不足 5 局。" + (mi === 3 && baseMode === "team" ? "（战队无禁用率数据）" : "");
  }

  /* ---------- 主渲染：分位归一化雷达 + 对照表 ---------- */
  function render() {
    var d = K.scopeOf(curScope);
    var list = currentList();
    var chosen = [];
    var seen = {};
    picked.forEach(function (name) {
      if (!name || seen[name]) return;
      var obj = list.filter(function (x) { return curName(x) === name; })[0];
      if (obj) { chosen.push(obj); seen[name] = 1; }
    });
    if (TREND[mode]) { renderTrend(chosen); return; }
    var M = MODES[mode];

    if (chosen.length < 2) { emptyTip("请至少选择 2 个对象"); return; }

    /* 分位归一化：每维取范围内全部对象的值，算被选对象所处的百分位 */
    var series = chosen.map(function (obj, ci) {
      return { name: M.name(obj), obj: obj, color: COLORS[ci] };
    });
    var universe = currentUniverse();
    var samePos = samePosMode();
    function weightOf(dim, x) {
      if (dim.weight) return Math.max(0, Number(dim.weight(x)) || 0);
      return Math.max(0, Number(x.games) || 0);
    }
    var dims = M.dims.map(function (dim) {
      // 分位与均值都基于「当前范围内全部合格对象」，不是只取候选列表的前 90 个
      var sorted = universe.map(function (x) { return K.mnum(dim.get(x, d)); })
        .filter(function (v) { return v !== null; })
        .sort(function (a, b) { return a - b; });
      var avgRaw = null;
      if (!samePos) {
        var sw = 0, sv = 0;
        universe.forEach(function (x) {
          var v = K.mnum(dim.get(x, d));
          if (v === null) return;
          var w = weightOf(dim, x);
          if (w > 0) { sv += v * w; sw += w; }
        });
        avgRaw = sw ? sv / sw : null;
      }
      return {
        label: dim.label,
        fmt: dim.fmt,
        avgRaw: avgRaw,
        avgScore: samePos ? 50 : (avgRaw === null ? 0 : Math.max(4, Math.min(100, pctRank(avgRaw, sorted)))),
        values: series.map(function (se) {
          var v = K.mnum(dim.get(se.obj, d));
          if (v === null) return { raw: null, score: 0 };   // 无有效样本 → 雷达顶点落圆心、表格显示 —
          var own = sorted;
          if (samePos) {
            own = universe.filter(function (x) { return x.pos === se.obj.pos; })
              .map(function (x) { return K.mnum(dim.get(x, d)); })
              .filter(function (x) { return x !== null; })
              .sort(function (a, b) { return a - b; });
          }
          var rank = pctRank(v, own);
          return { raw: v, score: Math.max(4, Math.min(100, rank === null ? 50 : rank)) };
        })
      };
    });

    /* 雷达图 */
    var W = 560, H = 472, CX = 280, CY = 246, R = 168, n = dims.length;
    function pt(i, r) {
      var a = -Math.PI / 2 + i * 2 * Math.PI / n;
      return [CX + Math.cos(a) * r, CY + Math.sin(a) * r];
    }
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="对比雷达图">';
    for (var ring = 1; ring <= 4; ring++) {
      var rr = R * ring / 4;
      var ringPts = dims.map(function (_, i) { return pt(i, rr).map(function (v) { return v.toFixed(1); }).join(","); }).join(" ");
      s += '<polygon points="' + ringPts + '" fill="' + (ring === 4 ? "rgba(157,178,204,.03)" : "none") +
        '" stroke=' + CP.grid + ' stroke-width="1"/>';
    }
    dims.forEach(function (dim, i) {
      var p = pt(i, R);
      s += '<line x1="' + CX + '" y1="' + CY + '" x2="' + p[0].toFixed(1) + '" y2="' + p[1].toFixed(1) + '" stroke=' + CP.grid + ' />';
      var lp = pt(i, R + 36);
      var anchor = lp[0] < CX - 12 ? "end" : lp[0] > CX + 12 ? "start" : "middle";
      s += '<text x="' + lp[0].toFixed(1) + '" y="' + (lp[1] + 4).toFixed(1) + '" text-anchor="' + anchor +
        '" font-size="12.5" fill=' + CP.label + ' font-family="Inter,PingFang SC,sans-serif">' + K.esc(dim.label) + "</text>";
    });
    series.forEach(function (se, ci) {
      var pts = dims.map(function (dim, i) {
        return pt(i, R * dim.values[ci].score / 100).map(function (v) { return v.toFixed(1); }).join(",");
      }).join(" ");
      s += '<polygon points="' + pts + '" fill="' + se.color + '" fill-opacity=".12" stroke="' + se.color +
        '" stroke-width="2" stroke-linejoin="round"/>';
      dims.forEach(function (dim, i) {
        var p = pt(i, R * dim.values[ci].score / 100);
        var tip = se.name + " · " + dim.label + "：" + dim.fmt(dim.values[ci].raw) +
          "（分位 " + Math.round(dim.values[ci].score) + "）";
        s += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="3" fill="' + se.color + '">' +
          '<title>' + K.esc(tip) + '</title></circle>';
      });
    });
    if (samePos || dims.every(function (dim) { return dim.avgRaw !== null; })) {
      var avgPts = dims.map(function (dim, i) {
        var r = samePos ? 50 : dim.avgScore;
        return pt(i, R * r / 100).map(function (v) { return v.toFixed(1); }).join(",");
      }).join(" ");
      s += '<polygon points="' + avgPts + '" fill="none" stroke="' + CP.label +
        '" stroke-width="1.5" stroke-dasharray="5 5" stroke-linejoin="round" opacity=".9"/>';
    }
    s += "</svg>";
    $("#radar").innerHTML = s;

    $("#legend").innerHTML = series.map(function (se) {
      var ic = M.icon(se.obj);
      return "<span><i style=\"background:" + se.color + '"></i>' +
        (ic ? '<img src="' + K.esc(ic) + '" alt="" style="width:20px;height:20px;border-radius:50%;object-fit:cover">' : "") +
        K.esc(se.name) + "</span>";
    }).join("") + (samePos || dims.every(function (dim) { return dim.avgRaw !== null; })
      ? '<span class="cmp-avg"><i class="dash"></i>' + (samePos ? "同位置中位 P50" : "范围均值") + '</span>' : "");

    /* 对照表 */
    var linkOf = function (se) {
      if (!M.target) return null;
      var key = M.targetKey ? se.obj[M.targetKey] : M.name(se.obj);
      return M.target + encodeURIComponent(key);
    };
    var head = "<thead><tr><th>指标</th>" + series.map(function (se) {
      var ic = M.icon(se.obj);
      var href = linkOf(se);
      var nameHTML = (ic ? '<img src="' + K.esc(ic) + '" alt="">' : "") + K.esc(se.name);
      return '<th><span class="cmp-head">' +
        (href ? '<a href="' + K.esc(href) + '" style="color:inherit;display:inline-flex;align-items:center;gap:6px">' + nameHTML + "</a>" : nameHTML) +
        "</span></th>";
    }).join("") + (samePos ? "" : '<th class="num cmp-avg-h" title="按局数/场次加权">范围均值</th>') +
      (series.length === 2 ? '<th class="num">' + (samePos ? "差（分位）" : "差（1−2）") + "</th>" : "") + "</tr></thead>";
    var body = "<tbody>" + dims.map(function (dim) {
      var raws = dim.values.map(function (v) { return v.raw; });
      var nums = raws.filter(function (v) { return v !== null; });   // 缺失值既不评最高/最低，也不参与差值
      var best = nums.length ? Math.max.apply(null, nums) : null;
      var worst = nums.length ? Math.min.apply(null, nums) : null;
      var cells = dim.values.map(function (v) {
        if (v.raw === null) return '<td><b style="color:var(--muted)">—</b></td>';
        var color = v.raw === best ? "var(--gold)" : (v.raw === worst && best !== worst ? "var(--muted)" : "");
        var pct = samePos && dim.label !== "出场局数"
          ? '<small class="cmp-pct">P' + Math.round(v.score) + "</small>" : "";
        return "<td><b" + (color ? ' style="color:' + color + '"' : "") + ">" + dim.fmt(v.raw) + "</b>" + pct + "</td>";
      }).join("");
      var diff = "";
      if (series.length === 2) {
        if (raws[0] === null || raws[1] === null) {
          diff = '<td class="num mono" style="color:var(--muted)">—</td>';
        } else if (samePos) {
          var ds = dim.values[0].score - dim.values[1].score;
          diff = '<td class="num mono" style="color:' + (ds >= 0 ? "#1F8A53" : "#D5374B") + '">' +
            (ds >= 0 ? "+" : "−") + Math.abs(Math.round(ds)) + " 分位</td>";
        } else {
          var dv = raws[0] - raws[1];
          // 指标格式可能自带符号（如 +1289），这里先剥掉再统一加差值的正负号
          var absTxt = String(dim.fmt(Math.abs(dv))).replace(/^[+＋\-−]/, "");
          diff = '<td class="num mono" style="color:' + (dv >= 0 ? "#1F8A53" : "#D5374B") + '">' +
            (dv >= 0 ? "+" : "−") + absTxt + "</td>";
        }
      }
      var avgCell = samePos ? "" : (dim.avgRaw === null
        ? '<td class="num cmp-avg-cell" title="当前范围没有有效样本">—</td>'
        : '<td class="num mono cmp-avg-cell" title="按局数/场次加权">' +
          dim.fmt(dim.avgRaw) + "</td>");
      return "<tr><td>" + K.esc(dim.label) + "</td>" + cells + avgCell + diff + "</tr>";
    }).join("") + "</tbody>";
    $("#cmpTable").innerHTML = head + body;
    renderInsights(series, dims, samePos);

    var hasNull = dims.some(function (dim) {
      return dim.values.some(function (v) { return v.raw === null; });
    });
    var tip = samePos
      ? "雷达位置 = 每名选手在自己位置内的百分位（0–100，外圈 = 更强）；虚线 = 同位置中位 P50；表格原始值下方的 Pxx 为同位置分位，选 2 个对象时的差值为分位差，缺失值不参与。表格每行最高值金色、最低值灰色；表头可点进详情页。"
      : "雷达位置 = 该指标在「" + K.scopeName(curScope) + "」全部 " + universe.length +
        " 个合格对象中的百分位（0–100，外圈 = 更强）；虚线 = 范围均值所在分位，表内「范围均值」按局数/场次加权（出场局数按对象等权），缺失值不参与。表格每行最高值金色、最低值灰色；选 2 个对象时多一列差值，表头可点进详情页。";
    if (hasNull) tip += " 表格里的「—」表示该对象在这一指标上没有有效样本，不参与最高/最低与差值计算，雷达图对应顶点落在圆心。";
    if (mode === "lane") {
      var cov = chosen.map(function (o) { return o.name + " " + o.n + " 人 / " + K.fmtInt(o.games) + " 局"; }).join("；");
      tip += " 分路按选手实际出场位置聚合、按局数加权（" + cov +
        "）。注意五种分路职责不同，KDA / 输出等原始值的天然区间不一样，只能读作「分路画像」，不能直接当成强弱排序；跨分路均值只作形状参考。";
    }
    if (mode === "player") {
      if (samePos) {
        tip += " 当前为同位置分位：每名选手只和同位置选手比；切「跨位置」可看全选手口径。";
      } else {
        tip += " 当前为跨位置分位：KDA / 输出会受位置影响，跨位置只读作个人画像；切「同位置」可做公平对比。";
      }
      if (posFilter !== "all") tip += " 位置筛选：「" + posFilter + "」。";
    }
    $("#cmpTip").textContent = tip;
  }

  /* ---------- URL 同步 / 读取 ---------- */
  function syncUrl() {
    try {
      var q = "?items=" + picked.filter(Boolean).map(encodeURIComponent).join(",") +
        (trendView && TRENDABLE[baseMode] ? "&trend=1" : "") +
        (baseMode === "player" && posFilter !== "all" ? "&pos=" + encodeURIComponent(posFilter) : "") +
        (baseMode === "player" && posNorm === "all" ? "&posnorm=all" : "");
      history.replaceState(null, "", location.pathname + q + location.hash);
    } catch (e) {}
  }
  function readUrl() {
    var sp = new URLSearchParams(location.search);
    trendView = sp.get("trend") === "1" && !!TRENDABLE[baseMode];
    var items = (sp.get("items") || "").split(",").filter(Boolean).map(decodeURIComponent);
    if (items.length) picked = [0, 1, 2, 3].map(function (i) { return items[i] || ""; });
    if (baseMode === "player") {
      var pos = sp.get("pos");
      if (pos) {
        posFilter = pos;
        var sel = document.getElementById("posFilter");
        if (sel) sel.value = pos;
      }
      var pn = sp.get("posnorm");
      if (pn === "all") {
        posNorm = "all";
        var psel = document.getElementById("posNorm");
        if (psel) psel.value = "all";
      }
    }
  }

  function wire() {
    var tabs = document.getElementById("modeTabs");
    if (tabs) {
      tabs.addEventListener("click", function (e) {
        var b = e.target.closest("button"); if (!b) return;
        Array.prototype.forEach.call(this.children, function (x) { x.classList.toggle("on", x === b); });
        baseMode = b.getAttribute("data-mode");
        if (!TRENDABLE[baseMode]) trendView = false;
        syncMode();
        picked = [null, null, null, null];
        populatePickers();
        render();
        syncUrl();
      });
    }
    var tt = document.getElementById("trendToggle");
    if (tt) tt.addEventListener("change", function () {
      if (!TRENDABLE[baseMode]) { this.checked = false; trendView = false; syncMode(); return; }
      trendView = this.checked;
      syncMode();
      picked = [null, null, null, null];
      populatePickers();
      render();
      syncUrl();
    });
    var tm = document.getElementById("trendMetric");
    if (tm) tm.addEventListener("change", render);
    var pf = document.getElementById("posFilter");
    if (pf) pf.addEventListener("change", function () {
      posFilter = this.value || "all";
      picked = [null, null, null, null];
      populatePickers();
      render();
      syncUrl();
    });
    var pn = document.getElementById("posNorm");
    if (pn) pn.addEventListener("change", function () {
      posNorm = this.value === "all" ? "all" : "pos";
      render();
      syncUrl();
    });
  }

  function init(baseModeIn) {
    if (booted) return;
    booted = true;
    K = window.KPL;
    $ = function (s) { return document.querySelector(s); };
    baseMode = MODES[baseModeIn] ? baseModeIn : "hero";
    trendView = false;
    mode = baseMode;
    posFilter = "all";
    posNorm = baseMode === "player" ? "pos" : "all";
    picked = [null, null, null, null];
    K.init();
    wire();
    curScope = K.scopeBar("#scopeBar", function (id) {
      curScope = id;
      picked = [null, null, null, null];
      populatePickers();
      render();
      syncUrl();
    });
    readUrl();
    syncMode();
    populatePickers();
    render();
    syncUrl();   // 打开页面即把「默认答案」写进 URL，便于直接分享当前对比
  }

  /* ---------- 分享图：把当前对比整理成一张 1080×1440 卡片的内容 ----------
     卡片 stats 只支持 2–6 行，所以每个对象压成一行（取该模式 2 个招牌指标）。 */
  var HEAD = { hero: ["胜率", "禁用率"], team: ["单局胜率", "大场胜率"],
               player: ["KDA", "胜率"], lane: ["KDA", "参团率"] };
  var KIND = { hero: "英雄对比", team: "战队对比", player: "选手对比", lane: "位置对比" };
  function spec() {
    if (!MODES[baseMode]) return null;
    var d = K.scopeOf(curScope);
    var list = currentList();
    var chosen = [];
    picked.forEach(function (name) {
      if (!name) return;
      var o = list.filter(function (x) { return curName(x) === name; })[0];
      if (o && chosen.indexOf(o) < 0) chosen.push(o);
    });
    if (chosen.length < 2) return null;
    var M = MODES[baseMode];
    var hdims = (HEAD[baseMode] || []).map(function (lbl) {
      return M.dims.filter(function (dm) { return dm.label === lbl; })[0];
    }).filter(Boolean);
    var stats = chosen.slice(0, 4).map(function (o) {
      var lbl = curName(o) + (baseMode === "lane" ? "（" + o.n + " 人）" : "");
      var val = hdims.map(function (dm) { return dm.label + " " + dm.fmt(dm.get(o, d)); }).join(" · ");
      return [lbl, val];
    });
    return {
      kind: KIND[baseMode],
      title: KIND[baseMode] + " · " + chosen.length + " 个对象",
      sub: K.scopeName(curScope) + " · 相对水平雷达口径",
      stats: stats,
      note: "卡片数值为各对象原始值；雷达位置是「" + K.scopeName(curScope) +
        "」范围内相对水平（越外越强）。" +
        (samePosMode() ? "当前为同位置分位，虚线为 P50。" : "当前为跨位置分位，虚线为加权范围均值。") +
        (baseMode === "player" && posFilter !== "all" ? "位置筛选：「" + posFilter + "」。" : "") +
        "来源：KPL 官方赛事数据。" +
        (baseMode === "lane" ? "分路按选手实际出场位置聚合、按局数加权。" : ""),
      url: location.href
    };
  }

  return { init: init, spec: spec, MAX: MAX };
})();
