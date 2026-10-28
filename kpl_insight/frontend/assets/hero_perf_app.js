/* 峡谷有数 · 英雄表现工作台
   数据：assets/hero_perf/index.js + assets/hero_perf/shard_*.js
   口径：选手 × 英雄 × 系列赛；P50/P75/P90 为同位置同英雄描述性参考。 */
(function () {
  "use strict";
  var K = window.KPL;
  var INDEX = window.KPL_HERO_PERF_INDEX || { players: [], leagues: [] };
  var DATA = {};
  var loaded = {}, loading = {};
  var player = "", scope = "all", hero = "all", selectedHero = "";
  var scopeReady = false;
  var wantedScope = "";
  var VERSION = "20261027c";
  var LEAGUE = {};
  (INDEX.leagues || []).forEach(function (l) { LEAGUE[String(l.id)] = l; });

  function $(s) { return document.querySelector(s); }
  function esc(v) { return K.esc(v); }
  function num(v, d) { var n = K.mnum(v); return n == null ? "—" : n.toFixed(d == null ? 1 : d); }
  function pct(v, d) { var n = K.mnum(v); return n == null ? "—" : n.toFixed(d == null ? 1 : d) + "%"; }
  function pClass(p) { return p == null ? "low" : p >= 75 ? "high" : p >= 50 ? "mid" : "low"; }
  function pBadge(p) { return p == null ? "" : '<span class="hp-p ' + pClass(p) + '">P' + Math.max(0, Math.min(100, Math.round(p))) + "</span>"; }
  function sampleTag(row) { return (row.series < 3 || row.games < 10) ? '<span class="hp-tag">小样本</span>' : ""; }
  function coverageText() {
    var c = INDEX.coverage || {};
    var parts = [];
    if (c.start) parts.push(c.start + " – " + c.end);
    if (c.players) parts.push(K.fmtInt(c.players) + " 名选手");
    if (c.games) parts.push(K.fmtInt(c.games) + " 局");
    return parts.join(" · ");
  }

  function playerEntry(name) {
    return (INDEX.players || []).filter(function (p) { return p.name === name; })[0] || null;
  }

  function loadShard(shard, cb) {
    if (loaded[shard]) { cb(); return; }
    if (loading[shard]) { loading[shard].push(cb); return; }
    loading[shard] = [cb];
    var s = document.createElement("script");
    s.src = "assets/hero_perf/shard_" + shard + ".js?v=" + VERSION;
    s.onload = function () {
      Object.assign(DATA, window.KPL_HERO_PERF_SHARD || {});
      loaded[shard] = true;
      var q = loading[shard] || [];
      delete loading[shard];
      q.forEach(function (fn) { try { fn(); } catch (e) { console.error(e); } });
      s.remove();
    };
    s.onerror = function () {
      delete loading[shard];
      $("#hpMeta").textContent = "数据分片加载失败，请刷新重试";
      s.remove();
    };
    document.head.appendChild(s);
  }

  function ensurePlayer(name, cb) {
    var entry = playerEntry(name);
    if (!entry) { cb(); return; }
    if (DATA[name]) { cb(); return; }
    loadShard(entry.shard, cb);
  }

  function scopeLabel() {
    return scope === "all" ? "全部赛事" : ((LEAGUE[scope] || {}).name || scope);
  }

  function rowsForScope(obj) {
    var out = [];
    (obj.heroes || []).forEach(function (h) {
      if (scope === "all") {
        out.push({
          hero: h.hero, heroId: h.heroId, heroIcon: h.heroIcon, pos: h.pos,
          series: h.series, games: h.games, wins: h.wins, wr: h.wr,
          kda: h.kda, dmgMin: h.dmgMin, goldMin: h.goldMin,
          part: h.part, deathsMin: h.deathsMin, bench: h.bench
        });
        return;
      }
      var lr = (h.leagues || []).filter(function (x) { return String(x.league) === String(scope); })[0];
      if (!lr) return;
      out.push({
        hero: h.hero, heroId: h.heroId, heroIcon: h.heroIcon, pos: lr.pos || h.pos,
        series: lr.series, games: lr.games, wins: lr.wins, wr: lr.wr,
        kda: lr.kda, dmgMin: lr.dmgMin, goldMin: lr.goldMin,
        part: lr.part, deathsMin: lr.deathsMin, bench: lr.bench,
        league: lr.league, leagueName: lr.leagueName
      });
    });
    out.sort(function (a, b) { return b.games - a.games || b.series - a.series; });
    return out;
  }

  function evidenceFor(obj, heroName) {
    var rows = (obj.seriesRows || []).filter(function (r) {
      if (scope !== "all" && String(r[2]) !== String(scope)) return false;
      if (heroName && r[6] !== heroName) return false;
      return true;
    });
    rows.sort(function (a, b) { return a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : (a[1] < b[1] ? 1 : -1); });
    return rows;
  }

  function fillPlayers() {
    var sel = $("#hpPlayer");
    var rows = (INDEX.players || []).slice();
    sel.innerHTML = rows.map(function (p) {
      return '<option value="' + esc(p.name) + '">' + esc(p.name) +
        " · " + esc(p.team) + " · " + esc(p.pos) + " · " + K.fmtInt(p.games) + " 局</option>";
    }).join("");
    var fromUrl = new URLSearchParams(location.search).get("player");
    player = fromUrl && rows.some(function (p) { return p.name === fromUrl; }) ? fromUrl : (rows[0] || {}).name || "";
    sel.value = player;
    sel.onchange = function () {
      player = this.value;
      hero = "all";
      selectedHero = "";
      loadPlayer();
    };
  }

  function fillScope(obj) {
    var sel = $("#hpScope");
    var seen = {};
    var leagues = [];
    ((obj && obj.heroes) || []).forEach(function (h) {
      (h.leagues || []).forEach(function (l) {
        var id = String(l.league);
        if (seen[id]) return;
        seen[id] = 1;
        leagues.push({ id: id, name: l.leagueName || id, year: l.year || 0 });
      });
    });
    leagues.sort(function (a, b) { return (b.year - a.year) || String(a.id).localeCompare(String(b.id)); });
    if (!scopeReady) {
      scope = wantedScope || "all";
      scopeReady = true;
    }
    if (scope !== "all" && !seen[scope]) scope = "all";
    sel.innerHTML = '<option value="all">全部赛事</option>' + leagues.map(function (l) {
      return '<option value="' + esc(l.id) + '">' + esc(l.name) + "</option>";
    }).join("");
    sel.value = scope;
    sel.onchange = function () {
      scope = this.value || "all";
      hero = "all";
      selectedHero = "";
      var current = DATA[player];
      if (current) fillHeroes(current);
      render();
      syncUrl();
    };
  }

  function fillHeroes(obj) {
    var sel = $("#hpHero");
    var rows = rowsForScope(obj);
    var names = rows.map(function (r) { return r.hero; });
    sel.innerHTML = '<option value="all">全部英雄</option>' + names.map(function (n) {
      return '<option value="' + esc(n) + '">' + esc(n) + "</option>";
    }).join("");
    hero = names.indexOf(hero) >= 0 ? hero : "all";
    sel.value = hero;
    sel.onchange = function () {
      hero = this.value || "all";
      selectedHero = hero === "all" ? "" : hero;
      render();
      syncUrl();
    };
  }

  function loadPlayer() {
    $("#hpMeta").textContent = "加载 " + player + " ...";
    ensurePlayer(player, function () {
      var obj = DATA[player];
      if (!obj) {
        $("#hpMeta").textContent = "未找到选手数据";
        return;
      }
      fillScope(obj);
      fillHeroes(obj);
      render();
      syncUrl();
    });
  }

  function renderSummary(obj, rows) {
    var ev = evidenceFor(obj, hero === "all" ? null : hero);
    var matches = {};
    ev.forEach(function (r) { matches[r[1]] = 1; });
    var games = rows.reduce(function (a, r) { return a + r.games; }, 0);
    var series = Object.keys(matches).length;
    var icon = obj.icon ? '<img class="hp-ava" src="' + esc(obj.icon) + '" alt="">' :
      '<span class="hp-ava ph">' + esc((obj.name || "?").slice(0, 1)) + "</span>";
    $("#hpSummary").innerHTML =
      '<div class="hp-id">' + icon +
        '<div><div class="hp-name">' + esc(obj.name) + "</div>" +
        '<div class="hp-sub">' + esc(obj.team || "—") + " · " + esc(obj.pos || "—") + " · " + esc(scopeLabel()) + "</div></div></div>" +
      '<div class="hp-kpis">' +
        '<div><b>' + K.fmtInt(series) + "</b><span>系列赛</span></div>" +
        '<div><b>' + K.fmtInt(games) + "</b><span>小局</span></div>" +
        '<div><b>' + K.fmtInt(rows.length) + "</b><span>英雄</span></div>" +
        '<div><b>' + K.fmtInt(obj.games) + "</b><span>生涯局数</span></div>" +
      "</div>";
  }

  function cell(value, p, digits, suffix) {
    var txt = value == null ? "—" : (digits == null ? String(value) : Number(value).toFixed(digits)) + (suffix || "");
    return '<td class="num">' + txt + " " + pBadge(p) + "</td>";
  }

  function renderTable(rows, obj) {
    var table = $("#hpHeroTable");
    if (!rows.length) {
      table.innerHTML = '<tbody><tr><td class="empty-tip">当前范围没有可用英雄</td></tr></tbody>';
      return;
    }
    var head = "<thead><tr><th>英雄</th><th class='num'>系列</th><th class='num'>局</th><th class='num'>战绩</th>" +
      "<th class='num'>胜率</th><th class='num'>KDA</th><th class='num'>分均伤害</th><th class='num'>分均经济</th>" +
      "<th class='num'>参团率</th><th class='num' title='每分钟死亡，越低越好'>死亡/分</th></tr></thead>";
    var body = "<tbody>" + rows.map(function (r) {
      var b = r.bench || { p: {} };
      var p = b.p || {};
      var wrDiff = b.leagueWr != null ? r.wr - b.leagueWr : null;
      var wrTitle = wrDiff == null ? "" : ' title="同英雄联盟胜率 ' + b.leagueWr + "%，相差 " + (wrDiff >= 0 ? "+" : "") + wrDiff.toFixed(1) + 'pp"';
      var ic = r.heroIcon ? '<img class="hp-hero-ic" src="' + esc(r.heroIcon) + '" alt="" loading="lazy">' : "";
      return '<tr data-hero="' + esc(r.hero) + '" tabindex="0">' +
        '<td><span class="hp-hero-cell">' + ic + '<b>' + esc(r.hero) + "</b>" + sampleTag(r) + "</span></td>" +
        '<td class="num">' + K.fmtInt(r.series) + "</td>" +
        '<td class="num">' + K.fmtInt(r.games) + "</td>" +
        '<td class="num">' + K.fmtInt(r.wins) + "–" + K.fmtInt(r.games - r.wins) + "</td>" +
        '<td class="num"><b' + wrTitle + ">" + pct(r.wr) + "</b></td>" +
        cell(r.kda, p.kda, 2) +
        cell(r.dmgMin, p.dmg, 0) +
        cell(r.goldMin, p.gold, 0) +
        cell(r.part, p.part, 1, "%") +
        cell(r.deathsMin, p.surv, 3) +
        "</tr>";
    }).join("") + "</tbody>";
    table.innerHTML = head + body;
    Array.prototype.forEach.call(table.querySelectorAll("tbody tr"), function (tr) {
      tr.classList.toggle("on", tr.getAttribute("data-hero") === selectedHero);
      function pick() {
        selectedHero = tr.getAttribute("data-hero");
        Array.prototype.forEach.call(table.querySelectorAll("tbody tr"), function (x) { x.classList.remove("on"); });
        tr.classList.add("on");
        renderDetail(obj, rows);
      }
      tr.addEventListener("click", pick);
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    });
  }

  function benchCard(label, value, p, ref, digits, suffix, lower) {
    var has = p != null && ref && ref[0] != null && ref[1] != null && ref[2] != null;
    var pv = p == null ? null : Math.max(0, Math.min(100, p));
    return '<div class="hp-bench">' +
      '<div class="hp-bench-top"><span>' + esc(label) + "</span>" + pBadge(p) + "</div>" +
      '<div class="hp-bench-val">' + (value == null ? "—" : Number(value).toFixed(digits) + (suffix || "")) + "</div>" +
      '<div class="hp-track' + (has ? "" : " off") + '">' +
        (has ? '<i style="left:' + pv.toFixed(1) + '%"></i>' +
          '<u style="left:50%"></u><u style="left:75%"></u><u style="left:90%"></u>' : "") +
      "</div>" +
      (has ? '<div class="hp-ref">P50 ' + Number(ref[0]).toFixed(digits) + " · P75 " + Number(ref[1]).toFixed(digits) +
        " · P90 " + Number(ref[2]).toFixed(digits) + (lower ? " · 越低越好" : "") + "</div>" :
        '<div class="hp-ref">基准不足</div>') +
      "</div>";
  }

  function trendLine(rows) {
    if (rows.length < 6) {
      return '<div class="hp-trend muted">系列赛 ' + rows.length + " 个，暂不生成趋势结论；单系列赛只展示事实。</div>";
    }
    var recent = rows.slice(0, 3), prev = rows.slice(3, 6);
    function median(rs, idx) {
      var vals = rs.map(function (r) { return r[idx]; })
        .filter(function (v) { return v != null && isFinite(Number(v)); })
        .map(Number)
        .sort(function (a, b) { return a - b; });
      if (!vals.length) return null;
      return vals.length % 2 ? vals[(vals.length - 1) / 2] : (vals[vals.length / 2 - 1] + vals[vals.length / 2]) / 2;
    }
    function delta(now, before) {
      if (now == null || before == null || before === 0) return null;
      return (now - before) / before * 100;
    }
    var dNow = median(recent, 11), dPrev = median(prev, 11);
    var kNow = median(recent, 10), kPrev = median(prev, 10);
    var dPct = delta(dNow, dPrev), kPct = delta(kNow, kPrev);
    function part(v) {
      if (v == null) return "—";
      return (v >= 0 ? "+" : "") + v.toFixed(1) + "%";
    }
    var volatile = (dPct != null && Math.abs(dPct) > 50) || (kPct != null && Math.abs(kPct) > 50);
    var noMetric = dPct == null && kPct == null;
    return '<div class="hp-trend"><b>近 3 个系列赛 vs 此前 3 个（中位数）</b>' +
      '<span>分均伤害 ' + part(dPct) + "</span>" +
      '<span>KDA ' + part(kPct) + "</span>" +
      (noMetric ? '<span class="hp-tag warn">有效指标不足</span>' :
        volatile ? '<span class="hp-tag warn">波动大，证据不足</span>' : "") +
      '<span class="muted">样本 ' + rows.length + " 个系列赛，仅描述变化，不作因果。</span></div>";
  }

  function renderDetail(obj, rows) {
    var row = rows.filter(function (r) { return r.hero === selectedHero; })[0] || rows[0];
    if (!row) {
      $("#hpDetail").innerHTML = '<div class="empty-tip">当前范围没有可用英雄</div>';
      $("#hpDetailTitle").textContent = "";
      return;
    }
    selectedHero = row.hero;
    var ev = evidenceFor(obj, row.hero);
    var b = row.bench;
    var p = (b && b.p) || {};
    var ref = (b && b.ref) || {};
    var hasP = b && ["kda", "dmg", "gold", "part", "surv"].some(function (k) { return p[k] != null; });
    var scopeTag = !hasP ? '<span class="hp-tag warn">基准不足</span>' :
      b.scope === "same-league" ? '<span class="hp-tag">同赛事基准</span>' :
      '<span class="hp-tag warn">基准已扩大：全历史</span>';
    var pool = b ? '<div class="hp-pool">' + (b.scope === "same-league" ? "同赛事" : "全历史") +
      "同位置同英雄 " + b.poolPlayers + " 人 / " + K.fmtInt(b.poolGames) + " 局 · 同英雄联盟 WR " +
      pct(b.leagueWr) + "（" + K.fmtInt(b.leagueGames) + " 局）" +
      (hasP ? "" : " · 有效样本不足，未评级") + "</div>" : "";
    $("#hpDetailTitle").textContent = row.hero + " · " + row.pos + " · " + scopeLabel();
    $("#hpDetail").innerHTML =
      '<div class="hp-detail-head"><div><b class="hp-detail-hero">' + esc(row.hero) + "</b>" +
        '<span class="hp-detail-sub">' + esc(row.pos) + " · " + K.fmtInt(row.series) + " 系列 / " +
        K.fmtInt(row.games) + " 局 / " + K.fmtInt(row.wins) + " 胜</span></div>" +
        '<div class="hp-detail-tags">' + sampleTag(row) + scopeTag + "</div></div>" +
      trendLine(ev) +
      '<div class="hp-bench-grid">' +
        benchCard("KDA", row.kda, p.kda, ref.kda, 2) +
        benchCard("分均伤害", row.dmgMin, p.dmg, ref.dmg, 0) +
        benchCard("分均经济", row.goldMin, p.gold, ref.gold, 0) +
        benchCard("参团率", row.part, p.part, ref.part, 1, "%") +
        benchCard("生存（死亡/分钟）", row.deathsMin, p.surv, ref.surv, 3, "", true) +
      "</div>" + pool +
      '<div class="hp-evidence-title">比赛证据 <em class="mono">' + ev.length + " 个系列赛</em>" +
        '<span class="hp-scroll-hint">表格可横向滚动 →</span></div>' +
      '<div class="hp-evidence-wrap"><table class="hp-evidence"><thead><tr>' +
        "<th>日期</th><th>对手</th><th>赛果</th><th class='num'>局</th><th class='num'>KDA</th>" +
        "<th class='num'>分均伤害</th><th class='num'>分均经济</th><th class='num'>参团</th><th class='num'>生存</th><th>证据</th>" +
      "</tr></thead><tbody>" +
      (ev.length ? ev.map(function (r) {
        var lg = LEAGUE[String(r[2])];
        var leagueName = lg ? lg.name : r[2];
        return "<tr><td>" + esc(r[0]) + '<small class="hp-league">' + esc(leagueName) + "</small></td>" +
          "<td>" + esc(r[4]) + "</td>" +
          '<td><span class="hp-result ' + (r[9] ? "w" : "l") + '">' + (r[9] ? "胜" : "负") + "</span></td>" +
          '<td class="num">' + r[7] + "</td>" +
          '<td class="num">' + num(r[10], 2) + "</td>" +
          '<td class="num">' + num(r[11], 0) + "</td>" +
          '<td class="num">' + num(r[12], 0) + "</td>" +
          '<td class="num">' + num(r[13], 1) + "%</td>" +
          '<td class="num">' + num(r[14], 3) + "</td>" +
          '<td><a href="match.html?id=' + encodeURIComponent(r[1]) + '">比赛 →</a></td></tr>';
      }).join("") : '<tr><td colspan="10" class="empty-tip">当前范围没有这个英雄的系列赛</td></tr>') +
      "</tbody></table></div>";
  }

  function render() {
    var obj = DATA[player];
    if (!obj) return;
    var allRows = rowsForScope(obj);
    var rows = hero === "all" ? allRows : allRows.filter(function (r) { return r.hero === hero; });
    if (!selectedHero || !rows.some(function (r) { return r.hero === selectedHero; })) {
      selectedHero = rows.length ? rows[0].hero : "";
    }
    renderSummary(obj, rows);
    renderTable(rows, obj);
    renderDetail(obj, rows);
    $("#hpMeta").textContent = "覆盖 " + (coverageText() || "—") + " · 更新 " + (INDEX.generatedAt || "—");
  }

  function syncUrl() {
    try {
      var q = "?player=" + encodeURIComponent(player);
      if (scope !== "all") q += "&league=" + encodeURIComponent(scope);
      if (hero !== "all") q += "&hero=" + encodeURIComponent(hero);
      history.replaceState(null, "", location.pathname + q);
    } catch (e) {}
  }

  function init() {
    K.init();
    wantedScope = new URLSearchParams(location.search).get("league") || "";
    var fromUrl = new URLSearchParams(location.search).get("hero");
    if (fromUrl) hero = fromUrl;
    fillPlayers();
    loadPlayer();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
