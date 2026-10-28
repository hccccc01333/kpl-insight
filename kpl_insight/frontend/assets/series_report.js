/* 系列赛深度分析 V1：只读 canonical report.json，不在前端重算。 */
(function () {
  "use strict";
  var K = window.KPL || {};
  var esc = K.esc || function (v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var $ = function (s, root) { return (root || document).querySelector(s); };
  var qs = new URLSearchParams(location.search);
  var matchId = qs.get("id") || "";
  var main = document.getElementById("main");
  if (!matchId || !main) return;

  function fmt(v, unit) {
    if (v == null || isNaN(v)) return "—";
    if (unit === "gold") return (v > 0 ? "+" : "") + Number(v).toLocaleString("en-US");
    if (unit === "prob") return (Number(v) * 100).toFixed(0) + "%";
    return String(v);
  }
  function tag(text, kind) {
    return '<span class="sr-tag ' + (kind || "") + '">' + esc(text) + "</span>";
  }
  function claimList(items, cls) {
    if (!items || !items.length) return '<div class="sr-empty">无</div>';
    return '<div class="sr-claims ' + cls + '">' + items.map(function (c) {
      return '<div class="sr-claim"><span class="sr-claim-dot"></span><p>' + esc(c.text) + "</p></div>";
    }).join("") + "</div>";
  }

  function gameCard(g) {
    var win = g.winner;
    var winSide = g.winner_side === 1 ? "蓝方" : "红方";
    var cp = g.checkpoints || {};
    var early = cp["8"] || {};
    var wins = (g.windows && g.windows.candidates) || [];
    var key = wins.filter(function (w) { return w.key; })[0] || wins[0];
    return '<article class="sr-game">' +
      '<div class="sr-game-hd"><span class="sr-g">G' + g.seq + "</span>" +
      '<span class="sr-win">' + esc(win) + " 胜</span>" +
      '<span class="sr-side">' + winSide + " · " + fmt(g.duration) + "′</span></div>" +
      '<div class="sr-game-meta">' + esc(g.team1) + " vs " + esc(g.team2) + "</div>" +
      '<div class="sr-game-kv"><span>8′金差（系列赛 team1）<b>' + fmt(early.gold_diff_series_team1, "gold") +
      "</b></span><span>早期领先<b>" + esc(g.early_leader || "—") + "</b></span>" +
      '<span>翻回<b>' + (g.comeback ? "是" : "否") + "</b></span></div>" +
      (key ? '<div class="sr-miniwin"><span class="sr-tag ' + (key.evidence_level === "estimate" ? "est" : "proxy") + '">' +
        (key.evidence_level === "estimate" ? "估算" : "代理") + "</span>" +
        '<b>' + fmt(key.start_minute, "min") + "–" + fmt(key.end_minute, "min") + "′</b> " +
        esc(key.favored_team) + " 占优 · " + (key.unit === "probability" ?
          fmt(key.from_value, "prob") + " → " + fmt(key.to_value, "prob") :
          fmt(key.from_value, "gold") + " → " + fmt(key.to_value, "gold")) +
        "</div>" : '<div class="sr-empty">无候选窗口</div>') +
      (g.final && g.final.is_full_game === false ?
        '<div class="sr-partial">末段累计异常已隔离；推塔/资源只到 ' + fmt(g.final.last_valid_minute, "min") + "′。</div>" : "") +
      "</article>";
  }

  function render(r) {
    var s = r.series, q = r.data_quality;
    var comp = r.series_comparison || {};
    var bp = r.bp || {};
    var degraded = q.status !== "ok";
    var games = (r.games || []).map(gameCard).join("");
    var sideSeq = (comp.side_sequence || []).map(function (x) {
      return "G" + x.seq + "：" + (x.team1_side === 1 ? s.team1 : s.team2) + " 蓝方";
    }).join(" · ");
    var common = (bp.common_picks || []).map(function (x) { return x.hero + " ×" + x.games; }).join("、") || "无";
    var warnings = (q.warnings || []).map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("");
    var html =
      '<section class="block sr-block" id="seriesAnalysis">' +
      '<div class="block-head"><h2><i></i>系列赛深度分析</h2>' +
      '<span class="block-note mono">V1 证据报告 · Python / 网站同源 JSON</span></div>' +
      '<div class="sr-card">' +
      '<div class="sr-kicker">SERIES EVIDENCE · ' + esc(s.date) + " · BO" + s.bo +
      " " + tag(degraded ? "数据降级" : "数据完整", degraded ? "warn" : "ok") + "</div>" +
      '<div class="sr-lead">' + esc(r.headline) + "</div>" +
      '<div class="sr-badges"><span>总局数 <b>' + q.games + "</b></span><span>分钟级 <b>" +
      q.games_with_minute_data + "/" + q.games + "</b></span><span>BP <b>" + q.games_with_bp + "/" + q.games +
      "</b></span><span>生成 <b>" + esc((r.generated_at || "").replace("T", " ")) + "</b></span></div>" +
      (warnings ? '<details class="sr-warnings"><summary>数据异常 / 隔离记录（' + q.warnings.length + "）</summary><ul>" +
        warnings + "</ul></details>" : "") +
      "</div>" +
      '<div class="sr-games">' + games + "</div>" +
      '<div class="sr-grid">' +
      '<div class="panel sr-panel"><div class="panel-title">系列赛横向对比</div>' +
      '<div class="sr-comp"><div><span>胜方</span><b>' + esc(comp.winner) + "</b></div>" +
      '<div><span>时长</span><b>' + fmt(comp.durations.min, "min") + "–" + fmt(comp.durations.max, "min") +
      "′ · 均 " + fmt(comp.durations.avg, "min") + "′</b></div>" +
      '<div><span>早期落后后翻回</span><b>' + ((comp.comeback_games || []).length ? "G" + comp.comeback_games.join("、G") : "无") + "</b></div>" +
      '<div class="sr-wide"><span>阵营顺序</span><b>' + esc(sideSeq) + "</b></div></div>" +
      '<div class="sr-note">金差按系列赛 team1 视角；8′ 使用目标分钟后的第一帧，不补造。</div></div>' +
      '<div class="panel sr-panel"><div class="panel-title">BP 事实</div>' +
      '<div class="sr-comp"><div><span>跨局重复 pick</span><b>' + esc(common) + "</b></div>" +
      '<div><span>BP 覆盖</span><b>' + q.games_with_bp + "/" + q.games + " 局</b></div></div>" +
      '<div class="sr-note">只陈述选禁重合，不推断教练意图或胜负原因。</div></div>' +
      "</div>" +
      '<div class="sr-grid sr-grid-3">' +
      '<div class="panel sr-panel"><div class="panel-title">直接事实</div>' + claimList(r.conclusion.facts, "fact") + "</div>" +
      '<div class="panel sr-panel"><div class="panel-title">统计判断</div>' + claimList(r.conclusion.inferences, "inf") + "</div>" +
      '<div class="panel sr-panel"><div class="panel-title">未证实假设</div>' + claimList(r.conclusion.hypotheses, "hyp") + "</div>" +
      "</div>" +
      '<div class="sr-limits">' + (r.limits || []).map(function (x) { return "· " + esc(x); }).join("<br>") + "</div>" +
      "</section>";
    var mount = document.createElement("div");
    mount.innerHTML = html;
    var section = mount.firstElementChild;
    // 放在复盘工作台之后、预测复盘/对局列表之前，作为本场的系列赛结论层。
    var anchor = main.querySelector("#liveZone") || main.querySelector("#histZone") || main.querySelector(".mnav");
    if (anchor && anchor.parentNode === main) main.insertBefore(section, anchor);
    else main.appendChild(section);
  }

  fetch("assets/series_reports/" + encodeURIComponent(matchId) + ".json", { cache: "no-cache" })
    .then(function (resp) {
      if (!resp.ok) return null;
      return resp.json();
    })
    .then(function (r) { if (r) render(r); })
    .catch(function () { /* 没有报告就保持页面原样 */ });
})();
