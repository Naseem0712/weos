/**
 * WEOS Universal Canvas — Viewport (world mm ↔ CSS px).
 * Zoom/pan are UI display state only — never mutate engineering W/H.
 * Batch D: safe min/max; resize preserves world center (no zoom reset).
 */
(function (global) {
  "use strict";

  var DEFAULT_LO = 0.15;
  var DEFAULT_HI = 6;

  function clampZoom(z, lo, hi) {
    if (global.WEOSCanvas && global.WEOSCanvas.commands && global.WEOSCanvas.commands.clampZoom) {
      return global.WEOSCanvas.commands.clampZoom(z);
    }
    lo = lo == null ? DEFAULT_LO : lo;
    hi = hi == null ? DEFAULT_HI : hi;
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
      padding = padding == null ? 48 : padding;
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

    /** Preserve world center when stage size changes (panel toggle). Does not reset zoom. */
    function preserveCenterOnResize(oldW, oldH, newW, newH) {
      var ow = Math.max(1, Number(oldW) || 1);
      var oh = Math.max(1, Number(oldH) || 1);
      var nw = Math.max(1, Number(newW) || 1);
      var nh = Math.max(1, Number(newH) || 1);
      var z = state.zoom || 1;
      var cx = (ow / 2 - state.panX) / z + state.worldOriginX;
      var cy = (oh / 2 - state.panY) / z + state.worldOriginY;
      state.panX = nw / 2 - (cx - state.worldOriginX) * z;
      state.panY = nh / 2 - (cy - state.worldOriginY) * z;
      return snapshot();
    }

    function applySnapshot(s) {
      if (!s) return;
      if (s.zoom != null) state.zoom = clampZoom(s.zoom);
      if (s.panX != null) state.panX = Number(s.panX) || 0;
      if (s.panY != null) state.panY = Number(s.panY) || 0;
      if (s.worldOriginX != null) state.worldOriginX = Number(s.worldOriginX) || 0;
      if (s.worldOriginY != null) state.worldOriginY = Number(s.worldOriginY) || 0;
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
      preserveCenterOnResize: preserveCenterOnResize,
      applySnapshot: applySnapshot,
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
