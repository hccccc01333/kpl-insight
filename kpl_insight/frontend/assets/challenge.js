/* 赛前预测挑战：localStorage 记录，无后端；只对已完赛的真实赛果结算 */
(function () {
  "use strict";
  var KEY = "kpl_predict_challenge_v1";
  var block = document.getElementById("challengeBlock");
  if (!block) return;
  var list = document.getElementById("chList");
  var stats = document.getElementById("chStats");
  var reset = document.getElementById("chReset");
  var loading = false, loaded = false;

  function esc(s) {
    if (window.KPL && KPL.esc) return KPL.esc(s);
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (x) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[x];
    });
  }
  function readStore() {
    try {
      var s = JSON.parse(localStorage.getItem(KEY) || "{}");
      if (!s || typeof s !== "object" || !s.picks || typeof s.picks !== "object") s = { picks: {} };
      return s;
    } catch (e) { return { picks: {} }; }
  }
  function saveStore(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  function nowStamp() {
    if (window.KPL && KPL.todayCN) return KPL.todayCN();
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function nowHM() {
    if (window.KPL && KPL.cnHM) return KPL.cnHM();
    var d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  function winnerOf(row) {
    if (!row || !row.done) return "";
    var a = Number(row.score1), b = Number(row.score2);
    if (!isFinite(a) || !isFinite(b) || a === b) return "";
    return a > b ? row.team1 : row.team2;
  }
  function pickable(row) {
    if (!row || row.done) return false;
    if (!row.team1 || !row.team2 || row.team1 === "待定" || row.team2 === "待定") return false;
    var d = nowStamp(), t = nowHM();
    return row.date > d || (row.date === d && (!row.time || String(row.time) > t));
  }
  function sortAsc(a, b) { return (a.date + " " + (a.time || "")).localeCompare(b.date + " " + (b.time || "")); }
  function sortDesc(a, b) { return (b.date + " " + (b.time || "")).localeCompare(a.date + " " + (a.time || "")); }

  function render() {
    if (!loaded) return;
    var all = window.KPL_SCHEDULE_ALL || [];
    var store = readStore();
    var upcoming = all.filter(pickable).sort(sortAsc).slice(0, 6);
    var recentDone = all.filter(function (r) { return r.done; }).sort(sortDesc).slice(0, 8);

    var resolved = 0, correct = 0, streak = 0, streakOpen = true;
    all.filter(function (r) { return r.done; }).sort(sortDesc).forEach(function (r) {
      var p = store.picks[String(r.matchId)];
      if (!p) return;
      var w = winnerOf(r);
      if (!w) return;
      resolved += 1;
      if (p.pick === w) {
        correct += 1;
        if (streakOpen) streak += 1;
      } else {
        streakOpen = false;
      }
    });

    stats.innerHTML =
      '<div class="item"><b>' + (resolved ? Math.round(correct / resolved * 100) + "%" : "—") + '</b><span>命中率</span></div>' +
      '<div class="item"><b>' + resolved + '</b><span>已结算</span></div>' +
      '<div class="item"><b>' + correct + '</b><span>命中</span></div>' +
      '<div class="item"><b>' + streak + '</b><span>当前连胜</span></div>';

    var html = "";
    if (upcoming.length) {
      html += '<div class="ch-sec"><b>待开赛 · 点队名记录选择</b><span class="mono">' + upcoming.length + " 场</span></div>";
      html += upcoming.map(function (r) {
        var id = String(r.matchId), p = store.picks[id];
        function btn(team) {
          return '<button type="button" class="ch-pick' + (p && p.pick === team ? " on" : "") +
            '" data-mid="' + esc(id) + '" data-team="' + esc(team) + '">' + esc(team) + "</button>";
        }
        return '<div class="ch-row"><div class="ch-meta"><span class="mono">' + esc(r.date + " " + (r.time || "")) +
          '</span><span>' + esc(r.leagueName || "") + (r.stage ? " · " + esc(r.stage) : "") + "</span></div>" +
          '<div class="ch-teams">' + btn(r.team1) + '<span class="ch-vs">VS</span>' + btn(r.team2) + "</div>" +
          '<div class="ch-state' + (p ? "" : " muted") + '">' + (p ? "已选：" + esc(p.pick) : "尚未选择") + "</div></div>";
      }).join("");
    } else {
      html += '<div class="ch-sec"><b>待开赛</b><span class="mono">暂无</span></div>' +
        '<div class="ch-muted">当前没有可预测的真实对阵。比赛日赛程更新后，这里会自动出现可选项。</div>';
    }

    html += '<div class="ch-sec"><b>最近赛果 · 自动结算</b><span class="mono">最近 ' + recentDone.length + " 场</span></div>";
    if (!recentDone.length) {
      html += '<div class="ch-muted">暂无已完赛记录。</div>';
    } else {
      html += recentDone.map(function (r) {
        var id = String(r.matchId), p = store.picks[id], w = winnerOf(r);
        var hit = p && w ? p.pick === w : null;
        return '<div class="ch-row"><div class="ch-meta"><a href="match.html?id=' + encodeURIComponent(id) + '"><span class="mono">' +
          esc(r.date) + "</span></a><span>" + esc(r.leagueName || "") + "</span></div>" +
          '<div class="ch-teams"><span class="ch-team">' + esc(r.team1) + '</span><b class="ch-score">' +
          esc(String(r.score1)) + " : " + esc(String(r.score2)) + '</b><span class="ch-team">' + esc(r.team2) + "</span></div>" +
          '<div class="ch-state ' + (hit === null ? "muted" : (hit ? "good" : "bad")) + '">' +
          (p ? "你的选择：" + esc(p.pick) + " · " + (hit === null ? "赛果待确认" : (hit ? "命中" : "未中")) : "未参与") +
          "</div></div>";
      }).join("");
    }
    list.innerHTML = html;
  }

  function loadSchedule() {
    if (window.KPL_SCHEDULE_ALL) { loaded = true; render(); return; }
    if (loading) return;
    loading = true;
    list.innerHTML = '<div class="ch-muted">正在加载赛程…</div>';
    var ref = document.querySelector('script[src*="assets/data.js"]');
    var query = (ref && ref.getAttribute("src").split("?")[1]) || "v=78";
    var s = document.createElement("script");
    s.src = "assets/schedule_all.js?" + query;
    s.onload = function () { loading = false; loaded = true; render(); };
    s.onerror = function () { loading = false; list.innerHTML = '<div class="ch-muted">赛程加载失败，请刷新重试。</div>'; };
    document.head.appendChild(s);
  }

  list.addEventListener("click", function (e) {
    var b = e.target.closest("button.ch-pick");
    if (!b) return;
    var store = readStore();
    store.picks[b.getAttribute("data-mid")] = { pick: b.getAttribute("data-team"), at: new Date().toISOString() };
    saveStore(store);
    render();
  });
  reset.addEventListener("click", function () {
    if (!window.confirm("清空全部预测记录？此操作不可撤销。")) return;
    try { localStorage.removeItem(KEY); } catch (e) {}
    render();
  });

  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      if (entries.some(function (x) { return x.isIntersecting; })) { io.disconnect(); loadSchedule(); }
    }, { rootMargin: "320px" });
    io.observe(block);
  } else {
    loadSchedule();
  }
})();
