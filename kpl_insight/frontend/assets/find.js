/* 智能找局：全部已归档小局的终局条件检索（无后端，不虚构缺失字段） */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var K = window.KPL || null;
  if (K && K.init) K.init();
  var INDEX = window.KPL_GAME_INDEX || {};
  var SCHEDULE = window.KPL_SCHEDULE_ALL || [];
  var BY_ID = Object.create(null);
  SCHEDULE.forEach(function (r) { BY_ID[String(r.matchId)] = r; });
  var LIMIT = 250;
  var esc = function (s) {
    if (K && K.esc) return K.esc(s);
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (x) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[x];
    });
  };
  var body = $("#findBody");
  var count = $("#fCount");
  var note = $("#findNote");

  // 选项：年份倒序、战队按中文排序
  var years = Array.from(new Set(SCHEDULE.map(function (r) { return String(r.year || (r.date || "").slice(0, 4)); })
    .filter(Boolean))).sort().reverse();
  var teams = Array.from(new Set(SCHEDULE.reduce(function (a, r) { if (r.team1) a.push(r.team1); if (r.team2) a.push(r.team2); return a; }, [])))
    .filter(function (t) { return t && t !== "待定"; })
    .sort(function (a, b) { return a.localeCompare(b, "zh-CN"); });
  years.forEach(function (y) { $("#fYear").insertAdjacentHTML("beforeend", '<option value="' + esc(y) + '">' + esc(y) + " 年</option>"); });
  teams.forEach(function (t) {
    $("#fTeam").insertAdjacentHTML("beforeend", '<option value="' + esc(t) + '">' + esc(t) + "</option>");
    $("#fWinner").insertAdjacentHTML("beforeend", '<option value="' + esc(t) + '">' + esc(t) + "</option>");
  });

  function params() {
    return {
      year: $("#fYear").value, team: $("#fTeam").value, winner: $("#fWinner").value,
      durMin: $("#fDurMin").value.trim(), durMax: $("#fDurMax").value.trim(),
      seq: $("#fSeq").value, bp: $("#fBp").value,
    };
  }
  function applyUrl() {
    var q = new URLSearchParams(location.search);
    if (q.get("year")) $("#fYear").value = q.get("year");
    if (q.get("team")) $("#fTeam").value = q.get("team");
    if (q.get("winner")) $("#fWinner").value = q.get("winner");
    if (q.get("durMin")) $("#fDurMin").value = q.get("durMin");
    if (q.get("durMax")) $("#fDurMax").value = q.get("durMax");
    if (q.get("seq")) $("#fSeq").value = q.get("seq");
    if (q.get("bp")) $("#fBp").value = q.get("bp");
  }
  function writeUrl(p) {
    var q = new URLSearchParams();
    Object.keys(p).forEach(function (k) { if (p[k]) q.set(k, p[k]); });
    history.replaceState(null, "", location.pathname + (q.toString() ? "?" + q.toString() : ""));
  }

  function run() {
    var p = params();
    var min = p.durMin === "" ? -Infinity : Number(p.durMin);
    var max = p.durMax === "" ? Infinity : Number(p.durMax);
    var seq = p.seq === "" ? null : Number(p.seq);
    var out = [];
    Object.keys(INDEX).forEach(function (mid) {
      var m = BY_ID[mid];
      if (!m || !m.done) return;
      if (p.year && String(m.year || (m.date || "").slice(0, 4)) !== p.year) return;
      if (p.team && m.team1 !== p.team && m.team2 !== p.team) return;
      var rows = INDEX[mid].b || [];
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i], dur = Number(r[2]) || 0, winner = r[4] || "";
        if (!dur) continue;
        if (seq !== null && Number(r[1]) !== seq) continue;
        if (dur < min || dur > max) continue;
        if (p.winner && winner !== p.winner) continue;
        var flags = Number(r[5]) || 0;
        if (p.bp === "full" && !(flags & 1)) continue;
        if (p.bp === "lineup" && !(flags & 2)) continue;
        out.push({ mid: mid, bid: String(r[0]), seq: Number(r[1]), dur: dur, winner: winner, flags: flags, m: m });
      }
    });
    out.sort(function (a, b) { return (b.m.date || "").localeCompare(a.m.date || "") || a.mid.localeCompare(b.mid) || a.seq - b.seq; });
    var shown = out.slice(0, LIMIT);
    count.textContent = out.length ? "共 " + out.length + " 局" + (out.length > LIMIT ? " · 显示前 " + LIMIT : "") : "共 0 局";
    if (!shown.length) {
      body.innerHTML = '<tr><td colspan="8" style="color:var(--muted)">没有符合条件的对局，试试放宽条件。</td></tr>';
    } else {
      body.innerHTML = shown.map(function (x) {
        var m = x.m;
        var bp = (x.flags & 1) ? "完整 BP" : ((x.flags & 2) ? "阵容齐" : "—");
        return "<tr><td class=\"mono\">" + esc(m.date || "") + "</td>" +
          "<td>" + esc((m.leagueName || "") + (m.stage ? " · " + m.stage : "")) + "</td>" +
          '<td><a href="match.html?id=' + encodeURIComponent(x.mid) + '">' + esc(m.team1) + " vs " + esc(m.team2) + "</a></td>" +
          '<td class="num">' + esc(x.seq) + '</td><td class="num">' + esc(x.dur) + " 分</td>" +
          "<td>" + (x.winner ? esc(x.winner) : "—") + "</td><td>" + esc(bp) + "</td>" +
          '<td><a href="game.html?id=' + encodeURIComponent(x.bid) + '">对局 →</a></td></tr>';
      }).join("");
    }
    writeUrl(p);
  }

  $("#fRun").addEventListener("click", run);
  ["fYear", "fTeam", "fWinner", "fSeq", "fBp"].forEach(function (id) {
    $("#" + id).addEventListener("change", run);
  });
  ["fDurMin", "fDurMax"].forEach(function (id) {
    var t = null;
    $("#" + id).addEventListener("input", function () { clearTimeout(t); t = setTimeout(run, 180); });
  });
  $("#fReset").addEventListener("click", function () {
    ["fYear", "fTeam", "fWinner", "fDurMin", "fDurMax", "fSeq", "fBp"].forEach(function (id) { $("#" + id).value = ""; });
    run();
  });

  applyUrl();
  run();
})();
