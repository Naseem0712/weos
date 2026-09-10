/**
 * WEOS Canvas Batch D — Snap foundation (results always world mm).
 * Pixel tolerance is viewport-aware and never persisted as geometry units.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  function create(opts) {
    opts = opts || {};
    var state = {
      enabled: opts.enabled !== false,
      gridMm: Number(opts.gridMm) || 100,
      tolerancePx: Number(opts.tolerancePx) || 8,
      prefer: opts.prefer || ["grid", "edge", "center", "point"],
    };

    function snapPoint(xMm, yMm, context) {
      context = context || {};
      var x = Number(xMm) || 0;
      var y = Number(yMm) || 0;
      if (!state.enabled) {
        return { xMm: x, yMm: y, snapped: false, source: null, candidates: [] };
      }
      var zoom = Number(context.zoom) || 1;
      if (zoom <= 0 || !isFinite(zoom)) zoom = 1;
      var tolMm = state.tolerancePx / zoom;
      var candidates = [];
      var g = state.gridMm > 0 ? state.gridMm : 100;
      if (context.gridMm) g = Number(context.gridMm) || g;
      var gx = Math.round(x / g) * g;
      var gy = Math.round(y / g) * g;
      candidates.push({
        source: "grid",
        xMm: gx,
        yMm: gy,
        distMm: Math.hypot(gx - x, gy - y),
      });

      (context.elements || []).forEach(function (el) {
        var ex = Number(el.xMm) || 0;
        var ey = Number(el.yMm) || 0;
        var ew = Number(el.widthMm) || 0;
        var eh = Number(el.heightMm) || 0;
        [
          [ex, y],
          [ex + ew, y],
          [x, ey],
          [x, ey + eh],
          [ex, ey],
          [ex + ew, ey],
          [ex, ey + eh],
          [ex + ew, ey + eh],
        ].forEach(function (pt) {
          candidates.push({
            source: "edge",
            xMm: pt[0],
            yMm: pt[1],
            distMm: Math.hypot(pt[0] - x, pt[1] - y),
          });
        });
        var cx = ex + ew / 2;
        var cy = ey + eh / 2;
        candidates.push({
          source: "center",
          xMm: cx,
          yMm: cy,
          distMm: Math.hypot(cx - x, cy - y),
        });
      });

      var prefer = state.prefer;
      var best = null;
      for (var i = 0; i < prefer.length; i++) {
        var src = prefer[i];
        var pool = candidates.filter(function (c) {
          return c.source === src && c.distMm <= tolMm;
        });
        if (pool.length) {
          pool.sort(function (a, b) {
            return a.distMm - b.distMm;
          });
          best = pool[0];
          break;
        }
      }
      if (!best) {
        var near = candidates.filter(function (c) {
          return c.distMm <= tolMm;
        });
        if (near.length) {
          near.sort(function (a, b) {
            return a.distMm - b.distMm;
          });
          best = near[0];
        }
      }
      if (!best) {
        return {
          xMm: x,
          yMm: y,
          snapped: false,
          source: null,
          candidates: candidates.slice(0, 8),
          toleranceMm: tolMm,
          tolerancePx: state.tolerancePx,
        };
      }
      return {
        xMm: best.xMm,
        yMm: best.yMm,
        snapped: true,
        source: best.source,
        candidates: candidates.slice(0, 8),
        toleranceMm: tolMm,
        tolerancePx: state.tolerancePx,
      };
    }

    return {
      get enabled() {
        return state.enabled;
      },
      setEnabled: function (on) {
        state.enabled = !!on;
      },
      toggle: function () {
        state.enabled = !state.enabled;
        return state.enabled;
      },
      snapPoint: snapPoint,
      snapshot: function () {
        return {
          enabled: state.enabled,
          gridMm: state.gridMm,
          tolerancePx: state.tolerancePx,
        };
      },
    };
  }

  C.snap = { create: create };
})(typeof window !== "undefined" ? window : globalThis);
