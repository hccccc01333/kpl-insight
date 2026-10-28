/* KPLdata BP 赛事演播室 · 真实赛事 BP 展示，不生成虚构比赛数据 */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var K = window.KPL;
  if (K && K.init) K.init();
  var idx = window.KPL_GAME_INDEX || {};
  var schedule = window.KPL_SCHEDULE_ALL || [];
  var scopes = window.KPL_SEASONS && window.KPL_SEASONS.scopes || {};
  var heroIcons = Object.create(null);
  ((scopes.all || {}).heroes || []).forEach(function (h) {
    if (h && h.name && h.icon) heroIcons[h.name] = h.icon;
  });
  function esc(s) {
    return K && K.esc ? K.esc(s) : String(s == null ? "" : s).replace(/[&<>"']/g, function (x) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[x];
    });
  }
  function safeImage(s) {
    s = String(s || "");
    return /^(https?:\/\/|\/?assets\/)/i.test(s) ? esc(s) : "";
  }
  function image(hero) { return safeImage(heroIcons[hero]); }
  function status(text, failed) {
    $("#studioFeedback").textContent = text;
    $("#studioFeedback").classList.toggle("error", !!failed);
  }
  function hasBP(row) {
    return row && idx[String(row.matchId)] && idx[String(row.matchId)].b.some(function (r) { return (Number(r[5]) & 1) !== 0; });
  }
  var seen = Object.create(null);
  var matches = schedule.filter(function (r) {
    if (!hasBP(r) || seen[String(r.matchId)]) return false;
    seen[String(r.matchId)] = true;
    return true;
  }).sort(function (a, b) {
    return (String(b.date || "") + " " + String(b.time || "")).localeCompare(String(a.date || "") + " " + String(a.time || ""));
  });
  var byId = Object.create(null);
  matches.forEach(function (r) { byId[String(r.matchId)] = r; });
  var years = Array.from(new Set(matches.map(function (m) { return String(m.date || "").slice(0, 4); })))
    .filter(Boolean).sort().reverse();
  $("#yearSelect").insertAdjacentHTML("beforeend", years.map(function (y) {
    return '<option value="' + esc(y) + '">' + esc(y) + " 年</option>";
  }).join(""));

  var qs = new URLSearchParams(location.search);
  var currentId = byId[qs.get("match") || qs.get("id")] ? String(qs.get("match") || qs.get("id")) :
    matches.length ? String(matches[0].matchId) : "";
  var currentBid = String(qs.get("battle") || "");
  var requestedGame = Number(qs.get("g") || 0);
  var currentGame = null, gameRecords = null, gameIndex = [];
  var requestedMissingSeq = 0;
  var mode = qs.get("mode") === "draft" ? "draft" : "final";
  var step = Number(qs.get("step")), initialStep = Number.isFinite(step) && qs.has("step") ? step : null;
  var timer = null, loadingVersion = 0;
  var revealedHero = "";
  var cache = Object.create(null);
  var prefersReduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
    $("#playBtn").textContent = "▶";
    $("#playBtn").setAttribute("aria-label", "播放");
  }
  function updateUrl() {
    if (!currentId || !currentGame) return;
    var q = new URLSearchParams();
    q.set("match", currentId);
    q.set("g", String(currentGame.seq));
    q.set("step", String(step));
    q.set("mode", mode);
    history.replaceState(null, "", location.pathname + "?" + q.toString());
  }
  function buildMatchOptions() {
    var year = $("#yearSelect").value;
    var query = $("#matchQuery").value.trim().toLowerCase();
    var eligible = matches.filter(function (r) {
      return (!year || String(r.date || "").startsWith(year)) &&
        (!query || [r.team1, r.team2, r.leagueName, r.stage, r.date].join(" ").toLowerCase().includes(query));
    });
    var limited = eligible.slice(0, 150);
    var currentRow = byId[currentId];
    if (currentRow && eligible.indexOf(currentRow) >= 0 && limited.indexOf(currentRow) < 0) {
      limited.unshift(currentRow);
    }
    $("#matchSelect").innerHTML = limited.length ? limited.map(function (r) {
      return '<option value="' + esc(r.matchId) + '">' + esc(r.date || "") + " · " +
        esc(r.team1) + " vs " + esc(r.team2) + " · " + esc(r.leagueName || "") + "</option>";
    }).join("") : '<option value="">当前筛选没有可回放的比赛</option>';
    if (limited.some(function (r) { return String(r.matchId) === currentId; })) $("#matchSelect").value = currentId;
    else if (limited.length) $("#matchSelect").selectedIndex = 0;
  }
  function setupGameOptions() {
    gameIndex = (idx[currentId] && idx[currentId].b || []).filter(function (r) { return (Number(r[5]) & 1) !== 0; })
      .slice().sort(function (a, b) { return Number(a[1]) - Number(b[1]); });
    $("#gameSelect").innerHTML = gameIndex.length ? gameIndex.map(function (g) {
      return '<option value="' + esc(g[0]) + '">第 ' + esc(g[1]) + " 局" + (Number(g[5]) & 2 ? " · 阵容齐全" : "") + "</option>";
    }).join("") : '<option value="">本场暂无完整 BP</option>';
    var selected = gameIndex.filter(function (r) {
      return (currentBid && String(r[0]) === currentBid) || (!currentBid && requestedGame && Number(r[1]) === requestedGame);
    })[0] || gameIndex[0];
    requestedMissingSeq = requestedGame && !gameIndex.some(function (r) {
      return Number(r[1]) === requestedGame;
    }) ? requestedGame : 0;
    if (selected) $("#gameSelect").value = String(selected[0]);
    currentBid = selected ? String(selected[0]) : "";
    requestedGame = 0;
  }
  function loadLeague(lid) {
    if (!/^[\w-]+$/.test(String(lid))) return Promise.reject(Error("不合法的赛事标识"));
    if (!cache[lid]) {
      cache[lid] = fetch("assets/games/" + encodeURIComponent(lid) + ".json")
        .then(function (r) { if (!r.ok) throw Error("HTTP " + r.status); return r.json(); })
        .catch(function (err) { delete cache[lid]; throw err; });
    }
    return cache[lid];
  }
  function loadMatch() {
    stop();
    var request = ++loadingVersion;
    var info = idx[currentId];
    if (!info || !currentBid) {
      status("这场比赛没有完整 BP 数据。请更换比赛。", true);
      currentGame = null;
      return;
    }
    status("正在加载真实逐局数据…");
    loadLeague(info.lg).then(function (all) {
      if (request !== loadingVersion) return;
      gameRecords = all;
      var g = all[currentBid];
      if (!g || !Array.isArray(g.bp) || !g.bp.length) throw Error("这局没有有效 BP");
      currentGame = g;
      if (initialStep !== null && mode === "draft") step = Math.min(g.bp.length, Math.max(0, Math.floor(initialStep)));
      else step = mode === "draft" ? 0 : g.bp.length;
      initialStep = null;
      render();
      status("当前展示已归档的真实对局；阵容按已记录的选用顺序排列，不代表分路位置。" +
        (requestedMissingSeq ? " 第 " + requestedMissingSeq + " 局没有完整 BP 记录，已展示第 " + g.seq + " 局。" : ""));
      requestedMissingSeq = 0;
    }).catch(function (err) {
      if (request !== loadingVersion) return;
      currentGame = null;
      status("对局数据加载失败：" + err.message + "。请通过网站或本地 HTTP 服务器访问并重新选择。", true);
    });
  }
  function chosenActions() {
    if (!currentGame) return [];
    return currentGame.bp.slice(0, mode === "final" ? currentGame.bp.length : step);
  }
  function sidePicks(camp) {
    return chosenActions().filter(function (x) { return Number(x[0]) === camp && Number(x[1]) === 1; });
  }
  function sideBans(camp) {
    return chosenActions().filter(function (x) { return Number(x[0]) === camp && Number(x[1]) === 0; });
  }
  function drawLineup(camp) {
    var side = camp === 1 ? "blue" : "red";
    var picks = sidePicks(camp);
    var players = currentGame.players || [];
    var out = [];
    for (var i = 0; i < 5; i++) {
      var x = picks[i];
      if (!x) {
        out.push('<div class="studio-card studio-card-empty"><b>+</b><small>待选英雄</small></div>');
        continue;
      }
      var h = String(x[2] || "");
      var who = players.filter(function (p) { return Number(p.c) === camp && String(p.h) === h; })[0];
      var src = image(h);
      var cardImage = src ? '<div class="studio-card-art"><img class="studio-card-bg" src="' + src +
        '" alt=""><img class="studio-card-icon" src="' + src + '" alt=""><div class="studio-card-gradient"></div></div>' :
        '<div class="studio-card-art"><div class="studio-card-gradient"></div></div>';
      out.push('<div class="studio-card filled' + (h === revealedHero ? " new" : "") + '" title="' + esc(h) + (who ? " · " + esc(who.n) : "") + '">' +
        cardImage + '<span class="studio-card-index">PICK 0' + (i + 1) + '</span>' +
        '<div class="studio-card-meta"><strong>' + esc(h || "未知英雄") + '</strong><span>' +
        esc(who && who.n ? who.n : "选手未记录") + "</span></div></div>");
    }
    $("#" + side + "Lineup").innerHTML = out.join("");
    $("#" + side + "PickCount").textContent = picks.length + " / 5 已选";
    var bans = sideBans(camp);
    var banHtml = '<span class="studio-ban-label">BAN</span>' + bans.map(function (b) {
      var src = image(b[2]);
      return '<span class="studio-ban" title="' + esc(b[2]) + '">' +
        (src ? '<img src="' + src + '" alt="' + esc(b[2]) + '">' : '<b>×</b>') + "</span>";
    }).join("");
    for (var j = bans.length; j < 5; j++) banHtml += '<span class="studio-ban-placeholder" aria-hidden="true"></span>';
    $("#" + side + "Bans").innerHTML = banHtml;
  }
  function setLogo(element, url) {
    var src = safeImage(url);
    if (src) { element.src = src; element.hidden = false; }
    else { element.removeAttribute("src"); element.hidden = true; }
  }
  function renderHead() {
    var g = currentGame, row = byId[currentId] || {};
    $("#matchContext").textContent = (row.leagueName || "KPL 赛事") + (row.stage ? " · " + row.stage : "");
    $("#matchDate").textContent = (row.date || "") + " · 第 " + (g.seq || "—") + " 局";
    $("#nameBlue").textContent = g.t1 || "蓝方";
    $("#nameRed").textContent = g.t2 || "红方";
    setLogo($("#logoBlue"), g.i1);
    setLogo($("#logoRed"), g.i2);
    var done = !!row.done, score1 = row.score1, score2 = row.score2;
    var mapped = done && score1 != null && score2 != null &&
      (g.t1 === row.team1 || g.t1 === row.team2) && (g.t2 === row.team1 || g.t2 === row.team2);
    $("#blueSeries").textContent = mapped ? String(g.t1 === row.team1 ? score1 : score2) : "—";
    $("#redSeries").textContent = mapped ? String(g.t2 === row.team1 ? score1 : score2) : "—";
    $("#seriesNote").textContent = mapped ? "最终大场比分" : "第 " + g.seq + " 局";
    $("#winHint").textContent = g.win === 1 ? "本局胜方：" + g.t1 : (g.win === 2 ? "本局胜方：" + g.t2 : "本局赛果未确认");
    $("#stateChip").textContent = mode === "final" ? "最终阵容" : "第 " + step + " / " + g.bp.length + " 手";
    $("#dataHint").textContent = "真实赛事 BP · " + g.bp.length + " 个已记录动作";
    $("#detailLink").href = "match.html?id=" + encodeURIComponent(currentId);
    $("#gameLink").href = "game.html?id=" + encodeURIComponent(currentBid);
    var video = String(g.video || "");
    $("#videoLink").hidden = !/^https?:\/\//.test(video);
    if (!$("#videoLink").hidden) $("#videoLink").href = video;
  }
  function renderActions() {
    var g = currentGame, end = mode === "final" ? g.bp.length : step;
    $("#bpActions").innerHTML = g.bp.map(function (b, i) {
      var camp = Number(b[0]), pick = Number(b[1]) === 1, h = String(b[2] || "");
      var src = image(h), active = i < end, now = i === end - 1;
      return '<button type="button" class="studio-action ' + (camp === 1 ? "blue" : "red") +
        (active ? " past" : "") + (now ? " now" : "") + '" data-step="' + (i + 1) +
        '" aria-label="第 ' + (i + 1) + " 手，" + (camp === 1 ? "蓝方" : "红方") +
        (pick ? "选用" : "禁用") + esc(h) + '">' + (src ?
          '<img src="' + src + '" alt="" loading="lazy">' : '<div class="studio-action-icon">' + (pick ? "P" : "B") + "</div>") +
        '<small>' + (i + 1) + '</small><span>' + (camp === 1 ? "蓝" : "红") + " · " + (pick ? "选" : "禁") + "</span></button>";
    }).join("");
    $("#stepRange").max = String(g.bp.length);
    $("#stepRange").value = String(end);
    $("#stepText").textContent = end + " / " + g.bp.length;
    $("#draftMode").classList.toggle("active", mode === "draft");
    $("#finalMode").classList.toggle("active", mode === "final");
    $("#draftMode").setAttribute("aria-pressed", mode === "draft" ? "true" : "false");
    $("#finalMode").setAttribute("aria-pressed", mode === "final" ? "true" : "false");
    var item = $("#bpActions .now"), container = $(".studio-actions-scroll");
    if (item && container) {
      var left = item.offsetLeft - container.clientWidth / 2 + item.clientWidth / 2;
      container.scrollLeft = Math.max(0, left);
    }
  }
  function renderSeries() {
    var g = currentGame, idxRows = gameIndex.filter(function (r) { return Number(r[1]) < Number(g.seq); });
    var past = { 1:[], 2:[] }, team1 = String(g.t1 || ""), team2 = String(g.t2 || "");
    idxRows.forEach(function (row) {
      var older = gameRecords && gameRecords[String(row[0])];
      if (!older || !Array.isArray(older.bp)) return;
      older.bp.forEach(function (p) {
        if (Number(p[1]) !== 1) return;
        var team = Number(p[0]) === 1 ? older.t1 : older.t2;
        if (team === team1) past[1].push(p[2]);
        if (team === team2) past[2].push(p[2]);
      });
    });
    $("#priorLabel").textContent = "此前 " + idxRows.length + " 局";
    $("#previousPicks").innerHTML = [1, 2].map(function (camp) {
      var title = camp === 1 ? team1 : team2;
      var list = Array.from(new Set(past[camp]));
      return '<div class="studio-prev-team"><b title="' + esc(title) + '">' + esc(title) + '</b><div class="studio-prev-icons">' +
        (list.length ? list.map(function (h) { var src = image(h); return src ?
          '<img src="' + src + '" title="' + esc(h) + '" alt="' + esc(h) + '" loading="lazy">' :
          '<span title="' + esc(h) + '">' + esc(h) + "</span>"; }).join("") :
          '<span>没有已记录的先前选用英雄</span>') + "</div></div>";
    }).join("");
  }
  function renderStats() {
    var g = currentGame;
    var fmt = function (v) { return Number.isFinite(Number(v)) ? Number(v).toLocaleString("zh-CN") : "—"; };
    $("#postStats").innerHTML = [
      ["击杀 · 蓝 / 红", fmt(g.k1) + " / " + fmt(g.k2)],
      ["经济 · 蓝 / 红", fmt(g.g1) + " / " + fmt(g.g2)],
      ["本局时长", g.dur == null ? "—" : fmt(g.dur) + " 分钟"],
    ].map(function (s) {
      return '<div class="studio-stat"><span>' + esc(s[0]) + '</span><strong>' + esc(s[1]) + "</strong></div>";
    }).join("");
  }
  function render() {
    if (!currentGame) return;
    step = Math.max(0, Math.min(currentGame.bp.length, Math.floor(step) || 0));
    renderHead();
    drawLineup(1);
    drawLineup(2);
    renderActions();
    renderSeries();
    renderStats();
    updateUrl();
  }
  function setStep(n) {
    if (!currentGame) return;
    stop();
    mode = "draft";
    step = Math.max(0, Math.min(currentGame.bp.length, n));
    revealedHero = step > 0 && currentGame.bp[step - 1] && Number(currentGame.bp[step - 1][1]) === 1 ? String(currentGame.bp[step - 1][2]) : "";
    render();
    revealedHero = "";
  }
  function setMode(next) {
    if (!currentGame) return;
    stop();
    mode = next;
    step = mode === "final" ? currentGame.bp.length : 0;
    render();
  }
  function play() {
    if (!currentGame) return;
    if (timer) { stop(); return; }
    if (mode === "final" || step >= currentGame.bp.length) {
      mode = "draft";
      step = 0;
      render();
    }
    $("#playBtn").textContent = "❚❚";
    $("#playBtn").setAttribute("aria-label", "暂停");
    var rate = Number($("#speedSelect").value) || 1100;
    timer = setInterval(function () {
      if (!currentGame || step >= currentGame.bp.length) { stop(); return; }
      step += 1;
      revealedHero = Number(currentGame.bp[step - 1][1]) === 1 ? String(currentGame.bp[step - 1][2]) : "";
      render();
      revealedHero = "";
      if (step >= currentGame.bp.length) stop();
    }, rate);
  }
  function onMatchChange() {
    var selected = $("#matchSelect").value;
    if (!byId[selected]) return;
    currentId = selected;
    currentBid = "";
    requestedGame = 0;
    mode = "final";
    initialStep = null;
    setupGameOptions();
    loadMatch();
  }
  $("#yearSelect").addEventListener("change", function () {
    buildMatchOptions(); onMatchChange();
  });
  $("#matchQuery").addEventListener("input", function () {
    buildMatchOptions();
    if ($("#matchSelect").value && $("#matchSelect").value !== currentId) onMatchChange();
  });
  $("#matchSelect").addEventListener("change", onMatchChange);
  $("#gameSelect").addEventListener("change", function () {
    currentBid = $("#gameSelect").value;
    mode = "final";
    initialStep = null;
    loadMatch();
  });
  $("#draftMode").addEventListener("click", function () { setMode("draft"); });
  $("#finalMode").addEventListener("click", function () { setMode("final"); });
  $("#bpActions").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-step]");
    if (b) setStep(Number(b.dataset.step));
  });
  $("#stepRange").addEventListener("input", function () { setStep(Number(this.value)); });
  $("#startBtn").addEventListener("click", function () { setStep(0); });
  $("#endBtn").addEventListener("click", function () { setMode("final"); });
  $("#prevBtn").addEventListener("click", function () { if (currentGame) setStep(mode === "final" ? currentGame.bp.length - 1 : step - 1); });
  $("#nextBtn").addEventListener("click", function () { if (currentGame) setStep(mode === "final" ? currentGame.bp.length : step + 1); });
  $("#playBtn").addEventListener("click", play);
  $("#speedSelect").addEventListener("change", function () { if (timer) { stop(); play(); } });
  $("#copyLink").addEventListener("click", function () {
    if (!currentGame) return;
    var url = location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () {
        $("#copyLink").textContent = "已复制链接 ✓";
        setTimeout(function () { $("#copyLink").textContent = "复制当前画面链接 ↗"; }, 1600);
      }).catch(function () { window.prompt("复制当前页面链接：", url); });
    } else window.prompt("复制当前页面链接：", url);
  });
  document.addEventListener("visibilitychange", function () { if (document.hidden) stop(); });
  document.addEventListener("keydown", function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); if (currentGame) setStep(step - 1); }
    if (e.key === "ArrowRight") { e.preventDefault(); if (currentGame) setStep(step + 1); }
    if (e.code === "Space") { e.preventDefault(); play(); }
  });
  if (!matches.length) { status("赛事索引没有可使用的 BP 记录。", true); return; }
  buildMatchOptions();
  if (currentId && $("#matchSelect").value !== currentId) {
    $("#yearSelect").value = String(byId[currentId].date || "").slice(0, 4);
    buildMatchOptions();
  }
  setupGameOptions();
  loadMatch();
  if (prefersReduced) $("#bpExplanation").textContent += " 当前系统启用了减少动态效果，所有动画均已简化。";
})();
