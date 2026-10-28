/* 峡谷有数 · 教练任期与 BP 指纹 */
(function () {
  "use strict";
  var K = window.KPL;
  var D = window.KPL_COACH_DATA || { coaches: [], tenures: [], heroes: [], coverage: {} };
  var HEROES = D.heroes || [];
  var COACH = {}, TENURE = {};
  (D.coaches || []).forEach(function (c) { COACH[c.id] = c; });
  (D.tenures || []).forEach(function (t) { TENURE[t.id] = t; });
  var coachId = "", tenureId = "";

  function $(s) { return document.querySelector(s); }
  function esc(v) { return K.esc(v); }
  function pct(v, d) { var n = K.mnum(v); return n == null ? "—" : n.toFixed(d == null ? 1 : d) + "%"; }
  function pp(v) { var n = K.mnum(v); return n == null ? "—" : (n >= 0 ? "+" : "") + n.toFixed(1) + "pp"; }
  function heroName(i) { return (HEROES[i] || {}).name || ("英雄 " + i); }
  function heroIcon(i) { var h = HEROES[i] || {}; return h.icon ? '<img class="tbp-hicon" src="' + esc(h.icon) + '" alt="" loading="lazy">' : ""; }
  function teamIcon(t) { return t.teamIcon ? '<img class="coach-teamicon" src="' + esc(t.teamIcon) + '" alt="">' : '<span class="coach-teamicon ph">' + esc((t.team || "?").slice(0, 1)) + "</span>"; }
  function pBadge(p) { return p == null ? "" : '<span class="hp-p ' + (p >= 75 ? "high" : p >= 50 ? "mid" : "low") + '">P' + Math.round(p) + "</span>"; }
  function confLabel(c) {
    return c === "high" ? "官方/人工核验" : c === "medium" ? "社区赛季名单 · 待官方核验" : "低置信 · 仅作线索";
  }

  function coachTenures(id) {
    return (D.tenures || []).filter(function (t) { return t.coachId === id; }).sort(function (a, b) {
      return (b.validFrom || "").localeCompare(a.validFrom || "") || String(a.team).localeCompare(String(b.team));
    });
  }

  function fillCoaches() {
    var sel = $("#coachSelect");
    var rows = (D.coaches || []).slice().sort(function (a, b) { return b.bpGames - a.bpGames || String(a.name).localeCompare(String(b.name)); });
    sel.innerHTML = rows.map(function (c) {
      return '<option value="' + esc(c.id) + '">' + esc(c.name) + " · " + esc((c.teams || []).join(" / ")) + " · " + K.fmtInt(c.bpGames) + " BP 局</option>";
    }).join("");
    var q = new URLSearchParams(location.search);
    var wanted = q.get("coach") || "";
    var found = rows.filter(function (c) { return c.id === wanted || c.name === wanted; })[0];
    coachId = found ? found.id : (rows[0] || {}).id || "";
    sel.value = coachId;
    sel.onchange = function () {
      coachId = this.value;
      fillTenures();
      render();
      syncUrl();
    };
  }

  function fillTenures() {
    var sel = $("#tenureSelect");
    var rows = coachTenures(coachId);
    sel.innerHTML = rows.map(function (t) {
      return '<option value="' + esc(t.id) + '">' + esc(t.seasonName) + " · " + esc(t.team) + "</option>";
    }).join("");
    var q = new URLSearchParams(location.search);
    var wanted = q.get("tenure") || "";
    var found = rows.filter(function (t) { return t.id === wanted; })[0];
    tenureId = found ? found.id : (rows[0] || {}).id || "";
    sel.value = tenureId;
    sel.onchange = function () {
      tenureId = this.value;
      render();
      syncUrl();
    };
  }

  function summary(t, c) {
    var teams = (c.teams || []).join(" / ");
    $("#coachSummary").innerHTML =
      '<div class="coach-id">' + teamIcon(t) +
        '<div><div class="coach-name">' + esc(c.name) + "</div>" +
        '<div class="coach-sub">' + esc(teams) + " · " + esc(t.seasonName) + " · " + esc(t.team) + "</div></div></div>" +
      '<div class="coach-kpis">' +
        '<div><b>' + K.fmtInt(t.series.games) + "</b><span>大场</span></div>" +
        '<div><b>' + pct(t.series.wr) + "</b><span>大场胜率</span></div>" +
        '<div><b>' + K.fmtInt(t.bp.games) + "</b><span>完整 BP 局</span></div>" +
        '<div><b>' + K.fmtInt(c.tenures.length) + "</b><span>收录任期</span></div>" +
      "</div>";
  }

  function sourceBox(t) {
    var conf = String(t.confidence || "");
    $("#coachSource").innerHTML =
      '<div class="coach-source-head"><span class="coach-source-tag ' + esc(conf) + '">' + esc(confLabel(conf)) + "</span>" +
        '<span class="mono">verified ' + esc(t.verifiedAt || "—") + "</span></div>" +
      '<div class="coach-source-body">' +
        "<div><span>任期</span><b>" + esc(t.validFrom || "—") + " → " + esc(t.validTo || "—") + "</b></div>" +
        "<div><span>来源</span><b>" + (t.sourceUrl ? '<a href="' + esc(t.sourceUrl) + '" target="_blank" rel="noopener">' + esc(t.sourceType || "source") + " ↗</a>" : "—") + "</b></div>" +
        "<div><span>角色</span><b>主教练（head coach）</b></div>" +
        "<div><span>口径</span><b>赛季边界 · 未细化到任免日</b></div>" +
      "</div>" +
      '<div class="block-note">' + esc(t.note || "") + " 当前教练不能回填往年赛果；换帅 / 角色不明确不纳入 BP 归属。</div>";
  }

  function finger(t) {
    var b = t.bp;
    var picks = b.topPicks || [];
    $("#coachFingerprint").innerHTML =
      '<div class="coach-stat-grid">' +
        '<div><b>' + K.fmtInt(b.uniquePicks) + '</b><span>选用英雄</span><em>有效 ' + (b.effectiveHeroes == null ? "—" : b.effectiveHeroes) + " 个</em></div>" +
        '<div><b>' + pct(b.topShare) + '</b><span>最高选用占比</span><em>' + (b.topPick == null ? "—" : esc(heroName(b.topPick))) + "</em></div>" +
        '<div><b>' + K.fmtInt(b.uniqueBans) + '</b><span>禁用英雄</span><em>' + K.fmtInt(b.bans) + " 手</em></div>" +
        '<div><b>' + K.fmtInt(b.games) + '</b><span>BP 样本</span><em>' + K.fmtInt(b.picks) + " 个选用手位</em></div>" +
      "</div>" +
      '<div class="tbp-table-wrap" style="max-height:420px"><table id="coachPicksTable"></table></div>' +
      '<div class="block-note">选用率 = 该队选用手数 / 本任期全部选用手数；联盟率取同赛事全部完整 BP；Lift 只描述偏好强度，胜率是赛果描述。</div>';
    var table = $("#coachPicksTable");
    table.innerHTML = "<thead><tr><th>英雄</th><th class='num'>选用</th><th class='num'>选用率</th><th class='num'>联盟率</th>" +
      "<th class='num'>Lift</th><th class='num'>胜率</th><th class='num'>联盟胜率</th><th class='num'>差</th></tr></thead><tbody>" +
      (picks.length ? picks.map(function (r) {
        return "<tr><td><span class='tbp-hero-cell'>" + heroIcon(r.i) + "<b>" + esc(heroName(r.i)) + "</b></span></td>" +
          '<td class="num">' + K.fmtInt(r.p) + "</td>" +
          '<td class="num">' + pct(r.rate) + "</td>" +
          '<td class="num">' + pct(r.baseRate) + "</td>" +
          '<td class="num">' + (r.lift == null ? "—" : r.lift.toFixed(2) + "×") + "</td>" +
          '<td class="num"><b>' + pct(r.win) + "</b></td>" +
          '<td class="num">' + pct(r.baseWin) + "</td>" +
          '<td class="num"><span class="' + (r.win == null || r.baseWin == null ? "" : r.win >= r.baseWin ? "pos" : "neg") + '">' +
          pp(r.win == null || r.baseWin == null ? null : r.win - r.baseWin) + "</span></td></tr>";
      }).join("") : '<tr><td colspan="8" class="empty-tip">本任期没有完整 BP 选用</td></tr>') + "</tbody>";
  }

  function banPanel(list, el, label) {
    var box = $(el);
    if (!list || !list.length) { box.innerHTML = '<div class="empty-tip">暂无禁用</div>'; return; }
    box.innerHTML = '<div class="tbp-ban-list">' + list.map(function (r) {
      return '<div class="tbp-ban-row">' + heroIcon(r.i) + '<span class="tbp-ban-name">' + esc(heroName(r.i)) + "</span>" +
        '<span class="tbp-ban-num">' + K.fmtInt(r.n) + " 次</span><span class=\"tbp-ban-rate\">" + pct(r.rate) + "</span></div>";
    }).join("") + "</div>";
    box.insertAdjacentHTML("beforeend", '<div class="block-note">' + esc(label) + "</div>");
  }

  function combos(t) {
    var rows = (t.bp.combos || []).slice(0, 6);
    if (!rows.length) { $("#coachCombos").innerHTML = '<div class="empty-tip">组合样本不足</div>'; return; }
    $("#coachCombos").innerHTML = '<div class="tbp-table-wrap"><table class="tbp-compact"><thead><tr>' +
      "<th>组合</th><th class='num'>同队同局</th><th class='num'>组合率</th><th class='num'>Lift</th><th class='num'>胜率</th>" +
      "</tr></thead><tbody>" + rows.map(function (r) {
        return '<tr><td><span class="tbp-pair">' + heroIcon(r.a) + esc(heroName(r.a)) + "<i>+</i>" + heroIcon(r.b) + esc(heroName(r.b)) + "</span></td>" +
          '<td class="num">' + K.fmtInt(r.n) + "</td>" +
          '<td class="num">' + pct(r.rate) + "</td>" +
          '<td class="num">' + (r.lift == null ? "—" : r.lift.toFixed(2) + "×") + "</td>" +
          '<td class="num"><b>' + pct(r.win) + "</b></td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="block-note">组合只记录同队同局共现；Lift 相对两名英雄各自选用率，不代表组合强度或因果。</div>';
  }

  function tenureHistory(c) {
    var rows = coachTenures(c.id);
    $("#coachTenures").innerHTML = '<div class="tbp-table-wrap"><table class="tbp-compact"><thead><tr>' +
      "<th>赛季</th><th>战队</th><th>任期</th><th class='num'>大场</th><th class='num'>大场胜率</th><th class='num'>BP 局</th><th>来源</th>" +
      "</tr></thead><tbody>" + rows.map(function (r) {
        return '<tr data-tenure="' + esc(r.id) + '" tabindex="0" class="' + (r.id === tenureId ? "on" : "") + '">' +
          "<td>" + esc(r.seasonName) + "</td><td>" + esc(r.team) + "</td>" +
          "<td>" + esc(r.validFrom) + " → " + esc(r.validTo) + "</td>" +
          '<td class="num">' + K.fmtInt(r.series.games) + "</td>" +
          '<td class="num"><b>' + pct(r.series.wr) + "</b></td>" +
          '<td class="num">' + K.fmtInt(r.bp.games) + "</td>" +
          '<td><a href="' + esc(r.sourceUrl) + '" target="_blank" rel="noopener">来源 ↗</a></td></tr>';
      }).join("") + "</tbody></table></div>" +
      '<div class="block-note">同一教练换队 / 换赛季按任期分开；不把多个角色当作独立胜利累加。</div>';
    Array.prototype.forEach.call(document.querySelectorAll("#coachTenures tr[data-tenure]"), function (tr) {
      function pick() { tenureId = tr.getAttribute("data-tenure"); $("#tenureSelect").value = tenureId; render(); syncUrl(); }
      tr.addEventListener("click", pick);
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    });
  }

  function evidence(t) {
    var ev = (t.evidence || []).slice(0, 20);
    $("#coachEvidenceTitle").innerHTML = "BP 证据 <em class='mono'>" + ev.length + " 场（最多 20）</em>" +
      '<span class="hp-scroll-hint">表格可横向滚动 →</span>';
    var table = $("#coachEvidenceTable");
    if (!ev.length) { table.innerHTML = '<tbody><tr><td class="empty-tip">本任期没有完整 BP 证据</td></tr></tbody>'; return; }
    table.innerHTML = "<thead><tr><th>日期 / 赛段</th><th>对手</th><th class='num'>阵营</th><th class='num'>赛果</th><th>我方选用</th><th>我方禁用</th><th>对手禁用</th><th>证据</th></tr></thead><tbody>" +
      ev.map(function (r) {
        var names = function (arr) { return (arr || []).map(function (i) { return '<span class="tbp-hname">' + esc(heroName(i)) + "</span>"; }).join(""); };
        return "<tr><td>" + esc(r[0]) + '<small class="tbp-stage">' + esc(r[2] || "") + "</small></td>" +
          "<td>" + esc(r[3]) + "</td>" +
          '<td class="num">' + (r[4] === 1 ? "蓝方" : "红方") + "</td>" +
          '<td class="num"><span class="tbp-result ' + (r[5] ? "w" : "l") + '">' + (r[5] ? "胜" : "负") + "</span></td>" +
          "<td>" + names(r[6]) + "</td><td>" + names(r[7]) + "</td><td>" + names(r[9]) + "</td>" +
          '<td><a href="match.html?id=' + encodeURIComponent(r[1]) + '">比赛 →</a></td></tr>';
      }).join("") + "</tbody>";
  }

  function coveragePanel() {
    var c = D.coverage || {};
    var ex = D.exclusions || [];
    $("#coachCoverage").innerHTML =
      '<div class="coach-coverage-grid">' +
        '<div><b>' + K.fmtInt(c.teamSeasons) + '</b><span>纳入队-赛季</span></div>' +
        '<div><b>' + K.fmtInt(c.coaches) + '</b><span>教练</span></div>' +
        '<div><b>' + K.fmtInt(c.bpGames) + '</b><span>去重完整 BP 局</span></div>' +
        '<div><b>' + K.fmtInt(c.excludedTeamSeasons) + '</b><span>未纳入队-赛季</span></div>' +
      "</div>" +
      '<div class="block-note">来源：' + esc(D.sourceMode || "—") + "；" + esc(c.start || "") + " – " + esc(c.end || "") + "。只纳入赛季内主教练唯一的战队；中途换帅 / 角色不明确 " + K.fmtInt(c.excludedTeamSeasons) + " 个队-赛季不进入 BP 归属。</div>" +
      (ex.length ? '<div class="coach-exclusions"><div class="coach-exclusions-head">未纳入的队-赛季 <em class="mono">' + ex.length + "</em></div>" +
        ex.map(function (r) {
          return '<div class="coach-exclusion"><span>' + esc(r.seasonName || r.league) + " · " + esc(r.team) + "</span><b>" + esc(r.reason || "未说明") + "</b></div>";
        }).join("") + "</div>" : "");
  }

  function render() {
    var c = COACH[coachId], t = TENURE[tenureId];
    if (!c || !t) return;
    summary(t, c);
    sourceBox(t);
    finger(t);
    banPanel(t.bp.topBans, "#coachBans", "己方主动禁用占本任期全部禁用手的比例。");
    banPanel(t.bp.topAgainst, "#coachBansAgainst", "对手面对该队时的禁用；不代表该英雄强弱。");
    combos(t);
    tenureHistory(c);
    evidence(t);
    coveragePanel();
    $("#coachMeta").textContent = "数据更新 " + (D.generatedAt || "—") + " · 赛季名单口径 · " + K.fmtInt((D.coverage || {}).teamSeasons) + " 个队-赛季";
    $("#coachCareer").innerHTML =
      '<div class="coach-career-item"><b>' + K.fmtInt(c.series) + "</b><span>生涯大场样本</span></div>" +
      '<div class="coach-career-item"><b>' + pct(c.seriesWr) + "</b><span>生涯大场胜率</span></div>" +
      '<div class="coach-career-item"><b>' + K.fmtInt(c.bpGames) + "</b><span>生涯 BP 局</span></div>" +
      '<div class="coach-career-item"><b>' + pct(c.bpWr) + "</b><span>生涯 BP 胜率</span></div>";
  }

  function syncUrl() {
    try {
      var q = "?coach=" + encodeURIComponent(coachId) + "&tenure=" + encodeURIComponent(tenureId);
      history.replaceState(null, "", location.pathname + q);
    } catch (e) {}
  }

  function init() {
    K.init();
    fillCoaches();
    fillTenures();
    render();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
