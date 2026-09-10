/**
 * WEOS Canvas Batch D — Viewport drafting grid (display-only, world mm spacing).
 * Does not store grid lines as design geometry.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  function spacingForZoom(zoom, baseMm) {
    baseMm = baseMm == null ? 100 : baseMm;
    var z = Number(zoom) || 1;
    if (C.commands && C.commands.clampZoom) z = C.commands.clampZoom(z);
    var targetPx = 50;
    var minor = baseMm;
    while (minor * z < targetPx * 0.45 && minor < 5000) minor *= 2;
    while (minor * z > targetPx * 2.2 && minor > 10) minor /= 2;
    minor = Math.max(10, Math.round(minor));
    return { minorMm: minor, majorMm: minor * 5, zoom: z };
  }

  function create(opts) {
    opts = opts || {};
    var state = {
      visible: opts.visible !== false,
      baseMm: Number(opts.baseMm) || 100,
    };

    function paintInto(layerEl, viewport, worldBounds) {
      if (!layerEl) return;
      if (!state.visible) {
        layerEl.innerHTML = "";
        layerEl.style.display = "none";
        return;
      }
      layerEl.style.display = "block";
      var snap = viewport.snapshot();
      var sp = spacingForZoom(snap.zoom, state.baseMm);
      var bb = worldBounds || { minX: 0, minY: 0, maxX: 4000, maxY: 3000 };
      var pad = sp.majorMm * 2;
      var minX = Math.floor(((bb.minX || 0) - pad) / sp.minorMm) * sp.minorMm;
      var minY = Math.floor(((bb.minY || 0) - pad) / sp.minorMm) * sp.minorMm;
      var maxX = Math.ceil(((bb.maxX || 4000) + pad) / sp.minorMm) * sp.minorMm;
      var maxY = Math.ceil(((bb.maxY || 3000) + pad) / sp.minorMm) * sp.minorMm;
      var w = Math.max(1, maxX - minX);
      var h = Math.max(1, maxY - minY);

      var parts = [];
      parts.push(
        '<svg class="uc-grid-svg" xmlns="http://www.w3.org/2000/svg" width="' +
          w +
          '" height="' +
          h +
          '" style="overflow:visible;position:absolute;left:' +
          minX +
          "px;top:" +
          minY +
          'px;pointer-events:none">'
      );
      for (var x = minX; x <= maxX + 0.001; x += sp.minorMm) {
        var major = Math.abs(x / sp.majorMm - Math.round(x / sp.majorMm)) < 1e-6;
        parts.push(
          '<line x1="' +
            (x - minX) +
            '" y1="0" x2="' +
            (x - minX) +
            '" y2="' +
            h +
            '" stroke="' +
            (major ? "rgba(20,40,60,.28)" : "rgba(20,40,60,.12)") +
            '" stroke-width="' +
            (major ? 1.5 : 1) +
            '"/>'
        );
      }
      for (var y = minY; y <= maxY + 0.001; y += sp.minorMm) {
        var majY = Math.abs(y / sp.majorMm - Math.round(y / sp.majorMm)) < 1e-6;
        parts.push(
          '<line x1="0" y1="' +
            (y - minY) +
            '" x2="' +
            w +
            '" y2="' +
            (y - minY) +
            '" stroke="' +
            (majY ? "rgba(20,40,60,.28)" : "rgba(20,40,60,.12)") +
            '" stroke-width="' +
            (majY ? 1.5 : 1) +
            '"/>'
        );
      }
      parts.push("</svg>");
      layerEl.innerHTML = parts.join("");
      layerEl.style.transform =
        "translate(" + snap.panX + "px," + snap.panY + "px) scale(" + snap.zoom + ")";
      layerEl.style.transformOrigin = "0 0";
    }

    return {
      get visible() {
        return state.visible;
      },
      setVisible: function (on) {
        state.visible = !!on;
      },
      toggle: function () {
        state.visible = !state.visible;
        return state.visible;
      },
      spacingForZoom: function (z) {
        return spacingForZoom(z, state.baseMm);
      },
      paintInto: paintInto,
      snapshot: function () {
        return { visible: state.visible, baseMm: state.baseMm };
      },
    };
  }

  C.grid = { create: create, spacingForZoom: spacingForZoom };
})(typeof window !== "undefined" ? window : globalThis);
