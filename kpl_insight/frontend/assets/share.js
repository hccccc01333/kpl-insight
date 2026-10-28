/* 分享图工坊 · 固定尺寸卡片模板（纯前端 Canvas，无依赖）
   1080×1440：上半深色封面（赛事身份/标题/头像），下半白色数据区（指标/口径/来源）。
   所有卡片强制带「数据范围 + 口径 + 生成时间 + 来源」，避免脱离上下文传播。

   用法：
     SHARE.mount(容器元素, function () { return {kind, title, sub, icon, stats, note, url}; });
     SHARE.open(spec, fileName)   直接预览一张卡片（不挂按钮）
   字段：
     kind   卡片类型徽标，如 "选手档案"
     title  主体（选手名 / 战队名 / 比赛标题）
     sub    一行副标题（队伍·位置 / 对手与比分 / 数据范围）
     icon   可选：选手头像或战队队徽（圆形裁切）
     stats  [[标签, 数值], ...]  2–6 行，两列排布
     note   口径与样本说明
     url    可复现链接
*/
(function () {
  "use strict";

  var W = 1080, H = 1440;
  var FONT = '"Microsoft YaHei","PingFang SC","Hiragino Sans GB","Source Han Sans SC",sans-serif';
  var BG = "#17181E";
  var WHITE = "#FFFFFF";
  var INK = "#191B23";
  var MUTED = "#6E7480";
  var FAINT = "#A2A7B1";
  var LINE = "#E6E8EC";
  var BRAND = "#F02F55";
  var D_INK = "#FFFFFF";
  var D_MUTED = "#B9BDC6";
  var SPLIT = 780;

  function font(size, weight) { return (weight || 400) + " " + size + "px " + FONT; }

  function roundRect(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  function wrap(g, text, maxW, maxLines) {
    var out = [], line = "";
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (g.measureText(line + c).width > maxW && line) {
        out.push(line);
        line = c;
        if (maxLines && out.length === maxLines - 1) {
          var rest = text.slice(i);
          while (g.measureText(rest + "…").width > maxW && rest.length > 1) rest = rest.slice(0, -1);
          out.push(rest + "…");
          return out;
        }
      } else line += c;
    }
    if (line) out.push(line);
    return out;
  }

  function fmtTime() {
    if (window.KPL && KPL.todayCN && KPL.cnHM) return KPL.todayCN() + " " + KPL.cnHM();
    var d = new Date();
    function p(n) { return (n < 10 ? "0" : "") + n; }
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  function loadImage(url) {
    return new Promise(function (resolve) {
      if (!url) { resolve(null); return; }
      var img = new Image();
      img.crossOrigin = "anonymous";
      var done = false;
      var timer = setTimeout(function () { if (!done) { done = true; resolve(null); } }, 3500);
      img.onload = function () { if (!done) { done = true; clearTimeout(timer); resolve(img); } };
      img.onerror = function () { if (!done) { done = true; clearTimeout(timer); resolve(null); } };
      img.src = url;
    });
  }

  function drawMonogram(g, text, cx, cy, r) {
    g.save();
    g.beginPath();
    g.arc(cx, cy, r, 0, Math.PI * 2);
    g.closePath();
    g.fillStyle = "#24252D";
    g.fill();
    g.clip();
    g.fillStyle = "#FFFFFF";
    g.font = font(52, 800);
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(String(text || "K").slice(0, 2), cx, cy + 2);
    g.restore();
    g.textBaseline = "alphabetic";
    g.beginPath();
    g.arc(cx, cy, r, 0, Math.PI * 2);
    g.strokeStyle = BRAND;
    g.lineWidth = 4;
    g.stroke();
  }

  function drawIcon(g, img, cx, cy, r) {
    g.save();
    g.beginPath();
    g.arc(cx, cy, r, 0, Math.PI * 2);
    g.closePath();
    g.fillStyle = "#24252D";
    g.fill();
    g.clip();
    var side = Math.min(img.width, img.height);
    var sx = (img.width - side) / 2, sy = (img.height - side) / 2;
    g.drawImage(img, sx, sy, side, side, cx - r, cy - r, r * 2, r * 2);
    g.restore();
    g.beginPath();
    g.arc(cx, cy, r, 0, Math.PI * 2);
    g.strokeStyle = BRAND;
    g.lineWidth = 4;
    g.stroke();
  }

  function draw(spec, iconImg) {
    var cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    var g = cv.getContext("2d");

    /* ---------- 上半：深色封面 ---------- */
    g.fillStyle = BG;
    g.fillRect(0, 0, W, H);

    g.fillStyle = BRAND;
    roundRect(g, 72, 64, 38, 38, 8);
    g.fill();
    g.fillStyle = "#FFFFFF";
    g.font = font(24, 800);
    g.textAlign = "center";
    g.fillText("K", 91, 91);
    g.textAlign = "left";
    g.fillStyle = D_INK;
    g.font = font(28, 800);
    g.fillText("峡谷有数", 124, 92);
    g.fillStyle = D_MUTED;
    g.font = font(19);
    g.fillText("KPL INSIGHT", 124, 122);

    if (spec.kind) {
      g.font = font(22, 600);
      var kw = Math.min(g.measureText(spec.kind).width + 34, 380);
      g.strokeStyle = "rgba(255,255,255,.26)";
      g.lineWidth = 1.5;
      roundRect(g, W - 72 - kw, 70, kw, 42, 21);
      g.stroke();
      g.fillStyle = D_MUTED;
      g.textAlign = "center";
      g.fillText(spec.kind, W - 72 - kw / 2, 97, kw - 20);
      g.textAlign = "left";
    }

    var hasIcon = !!spec.icon || !!iconImg;
    var xText = hasIcon ? 232 : 72;
    var titleMaxW = W - xText - 88;
    if (hasIcon) {
      if (iconImg) drawIcon(g, iconImg, 144, 288, 56);
      else drawMonogram(g, spec.monogram || spec.title, 144, 288, 56);
    }

    var titleY = 286;
    g.fillStyle = D_INK;
    g.font = font(76, 800);
    var titleLines = wrap(g, String(spec.title || ""), titleMaxW, 2);
    titleLines.forEach(function (t, i) {
      g.fillText(t, xText, titleY + i * 90);
    });
    var afterTitle = titleY + (titleLines.length - 1) * 90;

    if (spec.sub) {
      g.fillStyle = D_MUTED;
      g.font = font(27);
      var subLines = wrap(g, String(spec.sub), titleMaxW, 2);
      subLines.forEach(function (t, i) {
        g.fillText(t, xText, afterTitle + 56 + i * 40);
      });
      afterTitle += 56 + (subLines.length - 1) * 40;
    }

    g.fillStyle = BRAND;
    g.fillRect(72, Math.min(afterTitle + 78, SPLIT - 60), 64, 5);

    g.save();
    g.globalAlpha = 0.045;
    g.fillStyle = "#FFFFFF";
    g.font = font(232, 900);
    g.textAlign = "right";
    g.fillText("KPL", W - 54, SPLIT - 42);
    g.restore();
    g.textAlign = "left";

    /* ---------- 下半：白色数据区 ---------- */
    g.fillStyle = WHITE;
    g.fillRect(0, SPLIT, W, H - SPLIT);

    var stats = (spec.stats || []).slice(0, 6);
    var cols = 2;
    var rows = Math.ceil(stats.length / cols);
    var pad = 72;
    var gapX = 56;
    var rowH = 108;
    var cellW = (W - pad * 2 - gapX) / 2;

    var gridH = rows * rowH;
    var gridTop = SPLIT + 62 + Math.max(0, (150 - gridH) / 2);

    stats.forEach(function (row, i) {
      var col = i % 2, r = Math.floor(i / 2);
      var x = pad + col * (cellW + gapX);
      var y = gridTop + r * rowH;
      g.textAlign = "left";
      g.fillStyle = MUTED;
      g.font = font(21, 500);
      g.fillText(String(row[0] || ""), x, y + 32);
      g.fillStyle = i === 0 ? BRAND : INK;
      var vSize = 42;
      g.font = font(vSize, 800);
      var v = String(row[1] == null ? "—" : row[1]);
      while (g.measureText(v).width > cellW && vSize > 26) {
        vSize -= 2;
        g.font = font(vSize, 800);
      }
      g.fillText(v, x, y + 86);
    });

    g.strokeStyle = LINE;
    g.lineWidth = 1.5;
    for (var r2 = 1; r2 < rows; r2++) {
      var yLine = gridTop + r2 * rowH - 14;
      g.beginPath();
      g.moveTo(pad, yLine);
      g.lineTo(W - pad, yLine);
      g.stroke();
    }
    var fullRows = Math.floor(stats.length / 2);
    if (fullRows > 0) {
      g.beginPath();
      g.moveTo(pad + cellW + gapX / 2, gridTop);
      g.lineTo(pad + cellW + gapX / 2, gridTop + fullRows * rowH - 20);
      g.stroke();
    }

    var noteY = gridTop + rows * rowH + 26;
    if (spec.note) {
      g.fillStyle = BRAND;
      g.fillRect(pad, noteY - 18, 3, 22);
      g.fillStyle = MUTED;
      g.font = font(21);
      var noteLines = wrap(g, String(spec.note), W - pad * 2 - 20, 3);
      noteLines.forEach(function (t, i) {
        g.fillText(t, pad + 16, noteY + i * 32);
      });
    }

    g.strokeStyle = LINE;
    g.lineWidth = 1.5;
    g.beginPath();
    g.moveTo(pad, H - 126);
    g.lineTo(W - pad, H - 126);
    g.stroke();
    g.fillStyle = FAINT;
    g.font = font(19);
    g.fillText("数据来源：KPL 官方赛事公开数据 · 生成时间 " + fmtTime(), pad, H - 86);
    if (spec.url) {
      var u = String(spec.url);
      try { u = decodeURIComponent(u); } catch (e) {}
      g.fillStyle = BRAND;
      g.font = font(20, 700);
      g.fillText(u.slice(0, 82), pad, H - 50);
    }
    return cv;
  }

  function preview(cv, name) {
    var old = document.getElementById("shareLayer");
    if (old) old.remove();
    var layer = document.createElement("div");
    layer.id = "shareLayer";
    layer.setAttribute("style",
      "position:fixed;inset:0;z-index:9999;background:rgba(10,11,15,.9);display:flex;" +
      "flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:20px;" +
      "backdrop-filter:blur(4px)");
    var img = document.createElement("img");
    img.src = cv.toDataURL("image/png");
    img.alt = "分享图预览";
    img.setAttribute("style", "max-width:min(92vw,420px);max-height:72vh;border-radius:12px;" +
      "box-shadow:0 24px 60px rgba(0,0,0,.55)");
    var bar = document.createElement("div");
    bar.setAttribute("style", "display:flex;gap:12px;align-items:center");
    var dl = document.createElement("a");
    dl.href = img.src;
    dl.download = name || "kpldata-share.png";
    dl.textContent = "下载 PNG";
    dl.setAttribute("style", "display:inline-flex;align-items:center;padding:10px 22px;border-radius:8px;" +
      "background:#F02F55;color:#fff;font:700 14px/1 " + FONT + ";text-decoration:none");
    var close = document.createElement("button");
    close.type = "button";
    close.textContent = "关闭";
    close.setAttribute("style", "padding:10px 22px;border-radius:8px;border:1px solid rgba(255,255,255,.28);" +
      "background:transparent;color:#fff;font:600 14px/1 " + FONT + ";cursor:pointer");
    close.onclick = function () { layer.remove(); };
    var tip = document.createElement("div");
    tip.setAttribute("style", "color:#B9BDC6;font:400 12px/1.7 " + FONT + ";text-align:center;max-width:420px");
    tip.textContent = "1080×1440 固定尺寸，已带数据口径与生成时间；请勿裁剪或改数后再传播。";
    bar.appendChild(dl);
    bar.appendChild(close);
    layer.appendChild(img);
    layer.appendChild(bar);
    layer.appendChild(tip);
    layer.onclick = function (e) { if (e.target === layer) layer.remove(); };
    document.addEventListener("keydown", function esc(e) {
      if (e.key === "Escape") { layer.remove(); document.removeEventListener("keydown", esc); }
    });
    document.body.appendChild(layer);
  }

  function renderAsync(spec) {
    return loadImage(spec.icon).then(function (img) { return draw(spec, img); });
  }

  window.SHARE = {
    mount: function (anchor, specFn, fileName) {
      if (!anchor || anchor.querySelector(".share-fab")) return;
      var host = anchor.querySelector(".wrap") || anchor;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn share-fab";
      btn.textContent = "生成分享图";
      btn.setAttribute("style", "margin-top:14px");
      btn.onclick = function () {
        if (window.KPL && KPL.track) KPL.track("share_click");
        var spec;
        try { spec = specFn(); } catch (e) { spec = null; }
        if (!spec || !spec.title) { btn.textContent = "暂无可用数据"; return; }
        renderAsync(spec).then(function (cv) { preview(cv, fileName); });
      };
      host.appendChild(btn);
    },
    open: function (spec, fileName) {
      if (window.KPL && KPL.track) KPL.track("share_click");
      renderAsync(spec).then(function (cv) { preview(cv, fileName); });
    },
    render: draw
  };
})();
