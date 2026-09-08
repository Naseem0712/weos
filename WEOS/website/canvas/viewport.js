/**
 * WEOS Universal Canvas — Viewport (world mm ↔ CSS px).
 * Zoom/pan are UI display state only — never mutate engineering W/H.
 */
(function (global) {
  "use strict";

  function clampZoom(z, lo, hi) {
    lo = lo == null ? 0.25 : lo;
    hi = hi == null ? 4 : hi;
    var n = Number(z);
    if (!isFinite(n) || n <= 0) n = 1;
    return Math.max(lo, Math.min(hi, Math.round(n * 100) / 100));
  }

  function createViewport(opts) {
    opts = opts || {};
    var state = {
      zoom: clampZoom(opts.zoom == null ? 1 : opts.zoom),
      panX: Number(opts.panX || 0),
      panY: Number(opts.panY || 0),
      worldOriginX: Number(opts.worldOriginX || 0),
      worldOriginY: Number(opts.worldOriginY || 0),
    };

    function worldToViewport(xMm, yMm) {
      return {
        x: (Number(xMm) - state.worldOriginX) * state.zoom + state.panX,
        y: (Number(yMm) - state.worldOriginY) * state.zoom + state.panY,
      };
    }

    function viewportToWorld(vx, vy) {
      var z = state.zoom || 1;
      return {
        xMm: (Number(vx) - state.panX) / z + state.worldOriginX,
        yMm: (Number(vy) - state.panY) / z + state.worldOriginY,
      };
    }

    function setZoom(next, centerVp) {
      var oldZ = state.zoom;
      var z = clampZoom(next);
      if (centerVp && oldZ > 0) {
        var wx = (centerVp.x - state.panX) / oldZ + state.worldOriginX;
        var wy = (centerVp.y - state.panY) / oldZ + state.worldOriginY;
        state.zoom = z;
        state.panX = centerVp.x - (wx - state.worldOriginX) * z;
        state.panY = centerVp.y - (wy - state.worldOriginY) * z;
      } else {
        state.zoom = z;
      }
      return state.zoom;
    }

    function zoomBy(factor, centerVp) {
      return setZoom(state.zoom * factor, centerVp);
    }

    function panBy(dx, dy) {
      state.panX += Number(dx) || 0;
      state.panY += Number(dy) || 0;
    }

    function reset() {
      state.zoom = 1;
      state.panX = 0;
      state.panY = 0;
    }

    function fit(bounds, viewportW, viewportH, padding) {
      padding = padding == null ? 40 : padding;
      var ww = Math.max(1, Number(bounds && bounds.width) || 1000);
      var wh = Math.max(1, Number(bounds && bounds.height) || 1000);
      var minX = Number(bounds && bounds.minX) || 0;
      var minY = Number(bounds && bounds.minY) || 0;
      state.worldOriginX = minX;
      state.worldOriginY = minY;
      var availW = Math.max(1, Number(viewportW) - 2 * padding);
      var availH = Math.max(1, Number(viewportH) - 2 * padding);
      state.zoom = clampZoom(Math.min(availW / ww, availH / wh));
      state.panX = padding;
      state.panY = padding;
      return state.zoom;
    }

    function snapshot() {
      return {
        zoom: state.zoom,
        panX: state.panX,
        panY: state.panY,
        worldOriginX: state.worldOriginX,
        worldOriginY: state.worldOriginY,
      };
    }

    return {
      worldToViewport: worldToViewport,
      viewportToWorld: viewportToWorld,
      setZoom: setZoom,
      zoomBy: zoomBy,
      panBy: panBy,
      reset: reset,
      fit: fit,
      clampZoom: clampZoom,
      snapshot: snapshot,
      get zoom() {
        return state.zoom;
      },
      get panX() {
        return state.panX;
      },
      get panY() {
        return state.panY;
      },
    };
  }

  global.WEOSCanvas = global.WEOSCanvas || {};
  global.WEOSCanvas.viewport = { create: createViewport, clampZoom: clampZoom };
})(typeof window !== "undefined" ? window : globalThis);
