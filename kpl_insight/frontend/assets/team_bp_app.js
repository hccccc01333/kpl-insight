/* 峡谷有数 · 战队 BP 风格工作台
   数据：assets/team_bp/index.js + shard_*.js
   口径：完整 20 手 BP；选用/禁用/赛果分离；BP 顺序暂不分析。 */
(function () {
  "use strict";
  var K = window.KPL;
  var INDEX = window.KPL_TEAM_BP_INDEX || { teams: [], heroes: [], leagues: [], baselines: {} };
  var DATA = {};
  var loaded = {}, loading = {};
  var VERSION = "20261027d";
  var team = "", scope = "all", selectedHero = 0;
  var scopeReady = false, wantedScope = "", wantedHero = "";
  var LEAGUE = {};
  (INDEX.leagues || []).forEach(function (l) { LEAGUE[String(l.id)] = l; });
  var HEROES = INDEX.heroes || [];

  function $(s) { return document.querySelector(s); }
  function esc(v) { return K.esc(v); }
  function mnum(v) { return K.mnum(v); }
  function pct(v, d) { var n = mnum(v); return n == null ? "—" : n.toFixed(d == null ? 1 : d) + "%"; }
  function pp(v) { var n = mnum(v); return n == null ? "—" : (n >= 0 ? "+" : "") + n.toFixed(1) + "pp"; }
  function num(v, d) { var n = mnum(v); return n == null ? "—" : n.toFixed(d == null ? 1 : d); }
  function heroIcon(i) { var h = HEROES[i] || {}; return h.icon ? '<img class="tbp-hicon" src="' + esc(h.icon) + '" alt="" loading="lazy">' : ""; }
  function heroName(i) { return (HEROES[i] || {}).name || ("英雄 " + i); }
  function pBadge(p) { return p == null ? "" : '<span class="hp-p ' + (p >= 75 ? "high" : p >= 50 ? "mid" : "low") + '">P' + Math.max(0, Math.min(100, Math.round(p))) + "</span>"; }
  function sampleTag(games) { return games < 10 ? '<span class="hp-tag warn">样本 &lt;10 局</span>' : ""; }
  function pctRank(vals, v) {
    if (!vals || vals.length < 2 || v == null) return null;
    var below = 0;
    for (var i = 0; i < vals.length; i++) { if (vals[i] < v) below++; else break; }
    return Math.min(100, below / (vals.length - 1) * 100);
  }

  function teamEntry(name) {
    return (INDEX.teams || []).filter(function (t) { return t.name === name; })[0] || null;
  }

  function loadShard(shard, cb) {
    if (loaded[shard]) { cb(); return; }
    if (loading[shard]) { loading[shard].push(cb); return; }
    loading[shard] = [cb];
    var s = document.createElement("script");
    s.src = "assets/team_bp/shard_" + shard + ".js?v=" + VERSION;
    s.onload = function () {
      Object.assign(DATA, window.KPL_TEAM_BP_SHARD || {});
      loaded[shard] = true;
      var q = loading[shard] || [];
      delete loading[shard];
      q.forEach(function (fn) { try { fn(); } catch (e) { console.error(e); } });
      s.remove();
    };
    s.onerror = function () {
      delete loading[shard];
      $("#tbpMeta").textContent = "数据分片加载失败，请刷新重试";
      s.remove();
    };
    document.head.appendChild(s);
  }

  function scopeLabel() {
    return scope === "all" ? "全部赛事" : ((LEAGUE[scope] || {}).name || scope);
  }
  function scopeOptions(meta) {
    var ids = (meta && meta.leagues) || [];
    return ids.slice().sort(function (a, b) {
      var ya = (LEAGUE[a] || {}).year || 0, yb = (LEAGUE[b] || {}).year || 0;
      return (yb - ya) || String(a).localeCompare(String(b));
    });
  }

  function fillTeams() {
    var sel = $("#tbpTeam");
    var rows = (INDEX.teams || []).slice();
    sel.innerHTML = rows.map(function (t) {
      return '<option value="' + esc(t.name) + '">' + esc(t.name) + " · " + K.fmtInt(t.games) + " 局</option>";
    }).join("");
    var fromUrl = new URLSearchParams(location.search).get("team");
    team = fromUrl && rows.some(function (t) { return t.name === fromUrl; }) ? fromUrl : (rows[0] || {}).name || "";
    sel.value = team;
    sel.onchange = function () {
      team = this.value;
      selectedHero = 0;
      loadTeam();
    };
  }

  function fillScope(meta) {
    var sel = $("#tbpScope");
    var ids = scopeOptions(meta);
    if (!scopeReady) {
      scope = wantedScope && (wantedScope === "all" || ids.indexOf(wantedScope) >= 0) ? wantedScope : "all";
      scopeReady = true;
    }
    if (scope !== "all" && ids.indexOf(scope) < 0) scope = "all";
    sel.innerHTML = '<option value="all">全部赛事</option>' + ids.map(function (id) {
      var l = LEAGUE[id] || {};
      return '<option value="' + esc(id) + '">' + esc(l.name || id) + "</option>";
    }).join("");
    sel.value = scope;
    sel.onchange = function () {
      scope = this.value || "all";
      selectedHero = clampHero();
      render();
      syncUrl();
    };
  }

  function clampHero() {
    var obj = DATA[team];
    if (!obj) return 0;
    var st = obj.scopes[scope];
    if (!st) return 0;
    if (wantedHero) {
      var i = HEROES.findIndex(function (h) { return h.name === wantedHero; });
      if (i >= 0 && (st.heroes || []).some(function (r) { return r[0] === i; })) { wantedHero = ""; return i; }
    }
    if (selectedHero && (st.heroes || []).some(function (r) { return r[0] === selectedHero; })) return selectedHero;
    var first = (st.heroes || []).slice().sort(function (a, b) { return b[1] - a[1] || (b[2] + b[3]) - (a[2] + a[3]); })[0];
    return first ? first[0] : 0;
  }

  function loadTeam() {
    $("#tbpMeta").textContent = "加载 " + team + " ...";
    var meta = teamEntry(team);
    if (!meta) { $("#tbpMeta").textContent = "未找到战队数据"; return; }
    if (DATA[team]) {
      fillScope(meta);
      selectedHero = clampHero();
      render();
      syncUrl();
      return;
    }
    loadShard(meta.shard, function () {
      if (!DATA[team]) { $("#tbpMeta").textContent = "未找到战队数据"; return; }
      fillScope(meta);
      selectedHero = clampHero();
      render();
      syncUrl();
    });
  }

  function stat(label, value, sub) {
    return '<div class="tbp-stat"><b>' + value + '</b><span>' + esc(label) + "</span>" + (sub ? '<em>' + esc(sub) + "</em>" : "") + "</div>";
  }

  function renderSummary(obj, st, meta) {
    var leagueCount = scope === "all" ? (meta.leagues || []).length : 1;
    var icon = obj.icon ? '<img class="tbp-ava" src="' + esc(obj.icon) + '" alt="">' :
      '<span class="tbp-ava ph">' + esc((obj.name || "?").slice(0, 1)) + "</span>";
    $("#tbpSummary").innerHTML =
      '<div class="tbp-id">' + icon + '<div><div class="tbp-name">' + esc(obj.name) + "</div>" +
      '<div class="tbp-sub">' + esc(scopeLabel()) + " · 完整 20 手 BP · " + K.fmtInt(st.games) + " 局</div></div></div>" +
      '<div class="tbp-kpis">' +
        '<div><b>' + K.fmtInt(st.games) + "</b><span>完整 BP 局</span></div>" +
        '<div><b>' + K.fmtInt(leagueCount) + "</b><span>覆盖赛事</span></div>" +
        '<div><b>' + K.fmtInt(st.wins) + "–" + K.fmtInt(st.games - st.wins) + "</b><span>胜负</span></div>" +
        '<div><b>' + pct(st.games ? st.wins / st.games * 100 : null) + "</b><span>赛果胜率</span></div>" +
      "</div>";
  }

  function renderStyle(st) {
    var picks = st.picks || 0;
    var counts = {};
    (st.heroes || []).forEach(function (r) { if (r[1] > 0) counts[r[0]] = r[1]; });
    var ranked = Object.keys(counts).map(function (i) { return { i: +i, n: counts[i] }; }).sort(function (a, b) { return b.n - a.n; });
    var hhi = picks ? ranked.reduce(function (a, x) { return a + Math.pow(x.n / picks, 2); }, 0) : 0;
    var eff = hhi ? 1 / hhi : 0;
    var top = ranked[0];
    var topShare = picks && top ? top.n / picks * 100 : null;
    var bans = (st.heroes || []).filter(function (r) { return r[2] > 0; }).length;
    var chips = ranked.slice(0, 5).map(function (x) {
      return '<button class="tbp-chip" data-hero="' + x.i + '">' + heroIcon(x.i) + esc(heroName(x.i)) +
        " <em>" + pct(x.n / picks * 100) + "</em></button>";
    }).join("");
    $("#tbpStyle").innerHTML =
      '<div class="tbp-stat-grid">' +
        stat("选用英雄", K.fmtInt(ranked.length), "全部 " + K.fmtInt(picks) + " 个选用手位") +
        stat("有效英雄数", eff ? eff.toFixed(1) : "—", "1 / HHI，越高越分散") +
        stat("最高选用占比", topShare == null ? "—" : pct(topShare), top ? heroName(top.i) : "无选用") +
        stat("己方禁用英雄", K.fmtInt(bans), "禁用 " + K.fmtInt(st.bans) + " 手") +
      "</div>" +
      '<div class="tbp-chip-head">最常用英雄 <em class="mono">选用率</em></div>' +
      '<div class="tbp-chips">' + (chips || '<span class="empty-tip">暂无选用</span>') + "</div>";
  }

  function renderEffect(st, meta) {
    var wr = st.games ? st.wins / st.games * 100 : null;
    var p = meta.pct;
    var hint = p == null ? "样本不足，不参与分位" : "同范围 " + K.fmtInt(meta.rankN) + " 支战队 · ≥10 局";
    $("#tbpEffect").innerHTML =
      '<div class="tbp-stat-grid">' +
        stat("赛果胜率", pct(wr), K.fmtInt(st.wins) + " 胜 / " + K.fmtInt(st.games - st.wins) + " 负") +
        stat("同范围胜率分位", p == null ? "—" : "P" + Math.round(p), hint) +
        stat("完整 BP 样本", K.fmtInt(st.games), st.games < 30 ? "样本偏小" : "仅描述，不作因果") +
        stat("选用 / 禁用", K.fmtInt(st.picks) + " / " + K.fmtInt(st.bans), "均为 5 手 / 局") +
      "</div>" +
      '<div class="tbp-effect-note">胜率是赛果描述，不是“BP 优势”或教练评分。偏好与胜率分开看；禁用资源不进入英雄胜率分母。</div>' +
      sampleTag(st.games);
  }

  function heroRows(st, base) {
    if (!st || !base) return [];
    var picks = st.picks || 0;
    var out = (st.heroes || []).map(function (r) {
      var i = r[0], p = r[1], pw = r[2], b = r[3], ob = r[4], op = r[5];
      var pickRate = picks ? p / picks * 100 : null;
      var basePickRate = base.picks ? base.pick[i] / base.picks * 100 : null;
      var lift = pickRate != null && basePickRate > 0 ? pickRate / basePickRate : null;
      var winRate = p ? pw / p * 100 : null;
      var baseW = base.pick[i] ? base.pickWins[i] / base.pick[i] * 100 : null;
      var diff = winRate != null && baseW != null ? winRate - baseW : null;
      return { i: i, p: p, pw: pw, b: b, ob: ob, op: op, pickRate: pickRate, basePickRate: basePickRate, lift: lift, winRate: winRate, baseW: baseW, diff: diff };
    });
    return out.sort(function (a, b) {
      return b.p - a.p || (b.b + b.ob) - (a.b + a.ob) || a.i - b.i;
    });
  }

  function renderHeroTable(rows, st) {
    var table = $("#tbpPicksTable");
    if (!rows.length) {
      table.innerHTML = '<tbody><tr><td class="empty-tip">当前范围没有完整 BP 数据</td></tr></tbody>';
      return;
    }
    var head = "<thead><tr><th>英雄</th><th class='num'>选用</th><th class='num'>选用率</th>" +
      "<th class='num'>联盟率</th><th class='num'>Lift</th><th class='num'>胜率</th>" +
      "<th class='num'>联盟胜率</th><th class='num'>差</th><th class='num'>对手禁</th></tr></thead>";
    var body = "<tbody>" + rows.map(function (r) {
      return '<tr data-hero="' + r.i + '" tabindex="0"' + (r.i === selectedHero ? ' class="on"' : "") + ">" +
        '<td><span class="tbp-hero-cell">' + heroIcon(r.i) + "<b>" + esc(heroName(r.i)) + "</b></span></td>" +
        '<td class="num">' + K.fmtInt(r.p) + "</td>" +
        '<td class="num">' + pct(r.pickRate) + "</td>" +
        '<td class="num">' + pct(r.basePickRate) + "</td>" +
        '<td class="num"><span class="tbp-lift ' + (r.lift == null ? "" : r.lift >= 1.2 ? "high" : r.lift < .8 ? "low" : "") + '">' + (r.lift == null ? "—" : r.lift.toFixed(2) + "×") + "</span></td>" +
        '<td class="num"><b>' + pct(r.winRate) + "</b></td>" +
        '<td class="num">' + pct(r.baseW) + "</td>" +
        '<td class="num"><span class="' + (r.diff == null ? "" : r.diff >= 0 ? "pos" : "neg") + '">' + pp(r.diff) + "</span></td>" +
        '<td class="num">' + K.fmtInt(r.ob) + "</td></tr>";
    }).join("") + "</tbody>";
    table.innerHTML = head + body;
    Array.prototype.forEach.call(table.querySelectorAll("tbody tr"), function (tr) {
      function pick() {
        selectedHero = +tr.getAttribute("data-hero");
        render();
        syncUrl();
      }
      tr.addEventListener("click", pick);
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    });
  }

  function renderHeroDetail(rows, st) {
    var row = rows.filter(function (r) { return r.i === selectedHero; })[0] || rows[0];
    if (!row) {
      $("#tbpHeroDetail").innerHTML = '<div class="empty-tip">当前范围没有英雄状态</div>';
      $("#tbpHeroTitle").textContent = "";
      return;
    }
    selectedHero = row.i;
    var sum = row.p + row.b + row.op + row.ob;
    var not = Math.max(0, st.games - sum);
    var states = [
      ["己方选用", row.p, "#F6C021"],
      ["己方禁用", row.b, "#E05B63"],
      ["对手选用", row.op, "#7BA7E0"],
      ["对手禁用", row.ob, "#A98AD9"],
      ["未出现", not, "#596579"]
    ];
    var bar = states.map(function (s) {
      var w = st.games ? s[1] / st.games * 100 : 0;
      return w > 0 ? '<i style="width:' + w.toFixed(2) + '%;background:' + s[2] + '" title="' + s[0] + " " + s[1] + '"></i>' : "";
    }).join("");
    var cards = states.map(function (s) {
      var rate = st.games ? s[1] / st.games * 100 : null;
      return '<div class="tbp-state"><span><i style="background:' + s[2] + '"></i>' + s[0] + "</span><b>" + K.fmtInt(s[1]) +
        "</b><em>" + pct(rate) + "</em></div>";
    }).join("");
    var note = row.p ? "该队选用 " + K.fmtInt(row.p) + " 局，胜率 " + pct(row.winRate) + "；同范围同英雄 " + pct(row.baseW) + "，相差 " + pp(row.diff) + "。" :
      "该队在本范围没有选用过这个英雄，只统计禁用 / 对手动作。";
    $("#tbpHeroTitle").textContent = heroName(row.i) + " · 五种竞争状态";
    $("#tbpHeroDetail").innerHTML =
      '<div class="tbp-hero-head">' + heroIcon(row.i) + '<div><b class="tbp-hero-name">' + esc(heroName(row.i)) + "</b>" +
        '<span class="tbp-hero-sub">完整 BP ' + K.fmtInt(st.games) + " 局 · 出现 " + K.fmtInt(sum) + " 局</span></div>" +
        sampleTag(row.p) + "</div>" +
      '<div class="tbp-statebar">' + bar + "</div>" +
      '<div class="tbp-state-grid">' + cards + "</div>" +
      '<div class="tbp-detail-note">' + note + "</div>" +
      '<div class="tbp-detail-metrics">' +
        '<div><span>选用率</span><b>' + pct(row.pickRate) + "</b><em>联盟 " + pct(row.basePickRate) + "</em></div>" +
        '<div><span>偏好 Lift</span><b>' + (row.lift == null ? "—" : row.lift.toFixed(2) + "×") + "</b><em>1.00× = 联盟同率</em></div>" +
        '<div><span>己方禁用率</span><b>' + pct(st.bans ? row.b / st.bans * 100 : null) + "</b><em>" + K.fmtInt(row.b) + " / " + K.fmtInt(st.bans) + " 手</em></div>" +
        '<div><span>对手禁用率</span><b>' + pct(st.oppBans ? row.ob / st.oppBans * 100 : null) + "</b><em>" + K.fmtInt(row.ob) + " / " + K.fmtInt(st.oppBans) + " 手</em></div>" +
      "</div>" +
      '<div class="block-note">五种状态互斥，分母是完整 BP 局数；禁用不进入英雄胜率分母。</div>';
  }

  function renderBans(rows, st) {
    function list(kindDiag) {
      var arr = rows.slice().sort(function (a, b) { return kindDiag === "self" ? b.b - a.b : b.ob - a.ob; });
      var denom = kindDiag === "self" ? st.bans : st.oppBans;
      arr = arr.filter(function (r) { return (kindDiag === "self" ? r.b : r.ob) > 0; }).slice(0, 10);
      if (!arr.length) return '<div class="empty-tip">暂无禁用记录</div>';
      return '<div class="tbp-ban-list">' + arr.map(function (r) {
        var n = kindDiag === "self" ? r.b : r.ob;
        return '<button class="tbp-ban-row" data-hero="' + r.i + '">' + heroIcon(r.i) +
          '<span class="tbp-ban-name">' + esc(heroName(r.i)) + "</span>" +
          '<span class="tbp-ban-num">' + K.fmtInt(n) + " 次</span>" +
          '<span class="tbp-ban-rate">' + pct(denom ? n / denom * 100 : null) + "</span></button>";
      }).join("") + "</div>";
    }
    $("#tbpBans").innerHTML = list("self");
    $("#tbpBansAgainst").innerHTML = list("against");
    Array.prototype.forEach.call(document.querySelectorAll("#tbpBans [data-hero], #tbpBansAgainst [data-hero]"), function (b) {
      b.addEventListener("click", function () { selectedHero = +b.getAttribute("data-hero"); render(); syncUrl(); });
    });
  }

  function renderCombos(st, rows) {
    var byHero = {};
    rows.forEach(function (r) { byHero[r.i] = r; });
    var combos = (st.combos || []).slice(0, 8);
    var box = $("#tbpCombos");
    if (!combos.length) { box.innerHTML = '<div class="empty-tip">同队同局组合样本不足（至少 2 局）</div>'; return; }
    var head = "<thead><tr><th>组合</th><th class='num'>同队同局</th><th class='num'>组合率</th><th class='num'>独立期望</th><th class='num'>Lift</th><th class='num'>胜率</th></tr></thead>";
    var body = "<tbody>" + combos.map(function (c) {
      var a = c[0], b = c[1], n = c[2], wins = c[3];
      var pa = byHero[a] ? byHero[a].p : 0, pb = byHero[b] ? byHero[b].p : 0;
      var rate = st.games ? n / st.games * 100 : null;
      var expected = st.games && st.picks ? (pa / st.games) * (pb / st.games) * 100 : null;
      var lift = expected ? rate / expected : null;
      return '<tr><td><span class="tbp-pair">' + heroIcon(a) + esc(heroName(a)) + "<i>+</i>" + heroIcon(b) + esc(heroName(b)) + "</span></td>" +
        '<td class="num">' + K.fmtInt(n) + "</td>" +
        '<td class="num">' + pct(rate) + "</td>" +
        '<td class="num">' + pct(expected) + "</td>" +
        '<td class="num">' + (lift == null ? "—" : lift.toFixed(2) + "×") + "</td>" +
        '<td class="num"><b>' + pct(n ? wins / n * 100 : null) + "</b></td></tr>";
    }).join("") + "</tbody>";
    box.innerHTML = '<div class="tbp-table-wrap"><table class="tbp-compact">' + head + body + "</table></div>" +
      '<div class="block-note">组合率 = 同队同局出现次数 / 本范围局数；独立期望 = 两名英雄各自选用率的乘积；Lift 只描述共现，不代表组合强度或 BP 优势。</div>';
  }

  function heroState(r, h) {
    if (r[7].indexOf(h) >= 0) return ["选用", "pick"];
    if (r[8].indexOf(h) >= 0) return ["禁用", "ban"];
    if (r[9].indexOf(h) >= 0) return ["被对手选用", "oppick"];
    if (r[10].indexOf(h) >= 0) return ["被对手禁用", "oppban"];
    return ["", ""];
  }

  function renderEvidence(obj, st) {
    var ev = (obj.evidence || []).filter(function (r) { return scope === "all" || String(r[2]) === String(scope); });
    var heroMode = selectedHero != null && selectedHero >= 0;
    if (heroMode) ev = ev.filter(function (r) { return r[7].indexOf(selectedHero) >= 0 || r[8].indexOf(selectedHero) >= 0 || r[9].indexOf(selectedHero) >= 0 || r[10].indexOf(selectedHero) >= 0; });
    ev = ev.slice(0, 30);
    var title = $("#tbpEvidenceTitle");
    if (title) title.innerHTML = "比赛证据 <em class='mono'>" + (heroMode ? heroName(selectedHero) + " · " : "") + ev.length + " 场（最多 30）</em><span class='hp-scroll-hint'>表格可横向滚动 →</span>";
    var table = $("#tbpEvidenceTable");
    if (!ev.length) { table.innerHTML = '<tbody><tr><td class="empty-tip">当前范围没有比赛证据</td></tr></tbody>'; return; }
    var head = "<thead><tr><th>日期 / 赛段</th><th>对手</th><th>赛事</th><th class='num'>阵营</th><th class='num'>赛果</th>" +
      "<th>我方选用</th><th>我方禁用</th><th>对手禁用</th><th>证据</th></tr></thead>";
    var body = "<tbody>" + ev.map(function (r) {
      var lg = LEAGUE[String(r[2])] || {};
      var names = function (arr) {
        return (arr || []).map(function (i) { return '<span class="tbp-hname">' + esc(heroName(i)) + "</span>"; }).join("");
      };
      var state = heroMode ? heroState(r, selectedHero) : null;
      return "<tr><td>" + esc(r[0]) + '<small class="tbp-stage">' + esc(r[3] || "") + "</small>" +
          (state && state[0] ? '<small class="tbp-state-tag ' + state[1] + '">' + state[0] + "</small>" : "") + "</td>" +
        "<td>" + esc(r[4]) + "</td>" +
        "<td>" + esc(lg.name || r[2]) + "</td>" +
        '<td class="num">' + (r[5] === 1 ? "蓝方" : "红方") + "</td>" +
        '<td class="num"><span class="tbp-result ' + (r[6] ? "w" : "l") + '">' + (r[6] ? "胜" : "负") + "</span></td>" +
        "<td>" + names(r[7]) + "</td>" +
        "<td>" + names(r[8]) + "</td>" +
        "<td>" + names(r[10]) + "</td>" +
        '<td><a href="match.html?id=' + encodeURIComponent(r[1]) + '">比赛 →</a></td></tr>';
    }).join("") + "</tbody>";
    table.innerHTML = head + body;
  }

  function render() {
    var obj = DATA[team];
    var meta = teamEntry(team);
    if (!obj || !meta) return;
    var st = obj.scopes[scope] || obj.scopes.all;
    if (!st) return;
    var base = (INDEX.baselines || {})[scope] || (INDEX.baselines || {}).all || { pick: [], pickWins: [], picks: 0, bans: 0, games: 0 };
    var rows = heroRows(st, base);
    if (!rows.some(function (r) { return r.i === selectedHero; })) selectedHero = rows.length ? rows[0].i : 0;
    renderSummary(obj, st, meta);
    renderStyle(st);
    renderEffect(st, meta.scopes[scope] || meta.scopes.all || {});
    renderHeroTable(rows, st);
    renderHeroDetail(rows, st);
    renderBans(rows, st);
    renderCombos(st, rows);
    renderEvidence(obj, st);
    $("#tbpMeta").textContent = "覆盖 " + coverageText() + " · 更新 " + (INDEX.generatedAt || "—");
  }

  function coverageText() {
    var c = INDEX.coverage || {};
    var parts = [];
    if (c.start) parts.push(c.start + " – " + c.end);
    if (c.games) parts.push(K.fmtInt(c.games) + " 局");
    if (c.teams) parts.push(K.fmtInt(c.teams) + " 支战队");
    return parts.join(" · ");
  }

  function syncUrl() {
    try {
      var q = "?team=" + encodeURIComponent(team);
      if (scope !== "all") q += "&league=" + encodeURIComponent(scope);
      if (selectedHero) q += "&hero=" + encodeURIComponent(heroName(selectedHero));
      history.replaceState(null, "", location.pathname + q);
    } catch (e) {}
  }

  function init() {
    K.init();
    wantedScope = new URLSearchParams(location.search).get("league") || "";
    wantedHero = new URLSearchParams(location.search).get("hero") || "";
    fillTeams();
    loadTeam();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
