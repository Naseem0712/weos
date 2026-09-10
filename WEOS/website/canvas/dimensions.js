/**
 * WEOS Canvas Batch D — Dimension overlay from engineering mm (not CSS px).
 * Separate layer from product SVG / connection lines.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  function buildForSelection(elements, selectedIds) {
    var ids = (selectedIds || []).map(String);
    var out = [];
    (elements || []).forEach(function (el) {
      if (ids.indexOf(String(el.elementId)) < 0) return;
      var w = Number(el.widthMm);
      var h = Number(el.heightMm);
      if (!isFinite(w) || !isFinite(h)) return;
      out.push({
        kind: "overall",
        elementId: el.elementId,
        widthMm: w,
        heightMm: h,
        xMm: Number(el.xMm) || 0,
        yMm: Number(el.yMm) || 0,
        labelW: Math.round(w) + " mm",
        labelH: Math.round(h) + " mm",
        source: "engineering_mm",
      });
    });
    return out;
  }

  function paintInto(layerEl, overlays, viewport) {
    if (!layerEl) return;
    if (!overlays || !overlays.length) {
      layerEl.innerHTML = "";
      return;
    }
    var snap = viewport.snapshot();
    var inv = 1 / (snap.zoom || 1);
    var parts = [];
    overlays.forEach(function (d) {
      var x = d.xMm;
      var y = d.yMm;
      var w = d.widthMm;
      var h = d.heightMm;
      // Screen-stable stroke/font via inverse scale so labels stay readable.
      var sw = 1.25 * inv;
      var fs = 12 * inv;
      parts.push(
        '<g class="uc-dim" data-element-id="' +
          String(d.elementId || "").replace(/"/g, "") +
          '">' +
          '<line x1="' +
          x +
          '" y1="' +
          (y + h + 18) +
          '" x2="' +
          (x + w) +
          '" y2="' +
          (y + h + 18) +
          '" stroke="#0a5a48" stroke-width="' +
          sw +
          '"/>' +
          '<text x="' +
          (x + w / 2) +
          '" y="' +
          (y + h + 18 - 4 * inv) +
          '" text-anchor="middle" font-size="' +
          fs +
          '" fill="#0a5a48" font-family="Segoe UI,sans-serif">' +
          String(d.labelW).replace(/</g, "") +
          "</text>" +
          '<line x1="' +
          (x + w + 18) +
          '" y1="' +
          y +
          '" x2="' +
          (x + w + 18) +
          '" y2="' +
          (y + h) +
          '" stroke="#0a5a48" stroke-width="' +
          sw +
          '"/>' +
          '<text x="' +
          (x + w + 18 + 4 * inv) +
          '" y="' +
          (y + h / 2) +
          '" text-anchor="start" dominant-baseline="middle" font-size="' +
          fs +
          '" fill="#0a5a48" font-family="Segoe UI,sans-serif">' +
          String(d.labelH).replace(/</g, "") +
          "</text>" +
          "</g>"
      );
    });
    var minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    overlays.forEach(function (d) {
      minX = Math.min(minX, d.xMm - 40);
      minY = Math.min(minY, d.yMm - 40);
      maxX = Math.max(maxX, d.xMm + d.widthMm + 80);
      maxY = Math.max(maxY, d.yMm + d.heightMm + 80);
    });
    var vbW = Math.max(1, maxX - minX);
    var vbH = Math.max(1, maxY - minY);
    layerEl.innerHTML =
      '<svg class="uc-dim-svg" xmlns="http://www.w3.org/2000/svg" width="' +
      vbW +
      '" height="' +
      vbH +
      '" style="overflow:visible;position:absolute;left:' +
      minX +
      "px;top:" +
      minY +
      'px;pointer-events:none"><g transform="translate(' +
      -minX +
      "," +
      -minY +
      ')">' +
      parts.join("") +
      "</g></svg>";
    layerEl.style.transform =
      "translate(" + snap.panX + "px," + snap.panY + "px) scale(" + snap.zoom + ")";
    layerEl.style.transformOrigin = "0 0";
  }

  C.dimensions = { buildForSelection: buildForSelection, paintInto: paintInto };
})(typeof window !== "undefined" ? window : globalThis);
