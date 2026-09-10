/**
 * WEOS Universal Canvas — Viewport (Canvas D3).
 * Authoritative world-mm → scale → pan → screen transform.
 * One CSS transform: translate(pan) scale(zoom) with origin 0,0.
 * Engineering W/H never mutated. Zoom is display-only.
 *
 * Fit priority (host):
 *   1) Fit Selected — explicit Fit / F when a leaf selection exists
 *   2) Fit Scene — loadScene, Reset View, filters, no selection
 *   3) Initial load / first async preview — Fit once, not on every property paint
 */
(function (global) {
  "use strict";

  var DEFAULT_LO = 0.15;
  var DEFAULT_HI = 6;
  var DEFAULT_PAD = 48;
  var FALLBACK_W = 1000;
  var FALLBACK_H = 1000;

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

  function safeNum(v, fallback) {
    var n = Number(v);
    return isFinite(n) ? n : fallback;
  }

  /**
   * Normalize engineering bounds. Never use SVG viewBox units here —
   * artwork is stretched into the element box; Fit uses widthMm/heightMm only.
   */
  function normalizeBounds(bounds) {
    var minX = safeNum(bounds && bounds.minX, 0);
    var minY = safeNum(bounds && bounds.minY, 0);
    var width = safeNum(bounds && bounds.width, 0);
    var height = safeNum(bounds && bounds.height, 0);
    var maxX = safeNum(bounds && bounds.maxX, minX + width);
    var maxY = safeNum(bounds && bounds.maxY, minY + height);
    if (!(width > 0)) width = Math.max(1, maxX - minX);
    if (!(height > 0)) height = Math.max(1, maxY - minY);
    if (!(width > 0) || !isFinite(width)) width = FALLBACK_W;
    if (!(height > 0) || !isFinite(height)) height = FALLBACK_H;
    if (!isFinite(minX)) minX = 0;
    if (!isFinite(minY)) minY = 0;
    return {
      minX: minX,
      minY: minY,
      maxX: minX + width,
      maxY: minY + height,
      width: width,
      height: height,
    };
  }

  function computeFit(bounds, viewportW, viewportH, padding) {
    var b = normalizeBounds(bounds);
    var pad = safeNum(padding, DEFAULT_PAD);
    if (!(pad >= 0)) pad = DEFAULT_PAD;
    var vw = Math.max(1, safeNum(viewportW, 800));
    var vh = Math.max(1, safeNum(viewportH, 600));
    if (b.height > b.width * 1.35) pad = Math.min(pad, 40);
    else if (b.width > b.height * 1.8) pad = Math.min(pad, 48);
    var availW = Math.max(1, vw - 2 * pad);
    var availH = Math.max(1, vh - 2 * pad);
    var raw = Math.min(availW / b.width, availH / b.height);
    if (!isFinite(raw) || raw <= 0) raw = 1;
    var zoom = clampZoom(raw);
    var cx = b.minX + b.width / 2;
    var cy = b.minY + b.height / 2;
    // CSS: screen = world * zoom + pan  (worldOrigin kept at 0 — no double offset)
    var panX = vw / 2 - cx * zoom;
    var panY = vh / 2 - cy * zoom;
    if (!isFinite(panX)) panX = pad;
    if (!isFinite(panY)) panY = pad;
    return {
      zoom: zoom,
      panX: panX,
      panY: panY,
      worldOriginX: 0,
      worldOriginY: 0,
      bounds: b,
      padding: pad,
      viewportW: vw,
      viewportH: vh,
    };
  }

  function createViewport(opts) {
    opts = opts || {};
    var state = {
      zoom: clampZoom(opts.zoom == null ? 1 : opts.zoom),
      panX: safeNum(opts.panX, 0),
      panY: safeNum(opts.panY, 0),
      // D3: keep at 0 so CSS translate(pan) scale(zoom) matches worldToViewport.
      worldOriginX: 0,
      worldOriginY: 0,
    };
    var diagEnabled = false;

    function worldToViewport(xMm, yMm) {
      return {
        x: (safeNum(xMm, 0) - state.worldOriginX) * state.zoom + state.panX,
        y: (safeNum(yMm, 0) - state.worldOriginY) * state.zoom + state.panY,
      };
    }

    function viewportToWorld(vx, vy) {
      var z = state.zoom || 1;
      if (!isFinite(z) || Math.abs(z) < 1e-12) z = 1;
      return {
        xMm: (safeNum(vx, 0) - state.panX) / z + state.worldOriginX,
        yMm: (safeNum(vy, 0) - state.panY) / z + state.worldOriginY,
      };
    }

    function setZoom(next, centerVp) {
      var oldZ = state.zoom;
      if (!isFinite(oldZ) || oldZ <= 0) oldZ = 1;
      var z = clampZoom(next);
      if (centerVp && isFinite(centerVp.x) && isFinite(centerVp.y)) {
        var wx = (centerVp.x - state.panX) / oldZ + state.worldOriginX;
        var wy = (centerVp.y - state.panY) / oldZ + state.worldOriginY;
        state.zoom = z;
        state.panX = centerVp.x - (wx - state.worldOriginX) * z;
        state.panY = centerVp.y - (wy - state.worldOriginY) * z;
      } else {
        state.zoom = z;
      }
      if (!isFinite(state.panX)) state.panX = 0;
      if (!isFinite(state.panY)) state.panY = 0;
      return state.zoom;
    }

    function zoomBy(factor, centerVp) {
      var f = Number(factor);
      if (!isFinite(f) || f <= 0) f = 1;
      return setZoom(state.zoom * f, centerVp);
    }

    function panBy(dx, dy) {
      state.panX += safeNum(dx, 0);
      state.panY += safeNum(dy, 0);
    }

    function reset() {
      state.zoom = 1;
      state.panX = 0;
      state.panY = 0;
      state.worldOriginX = 0;
      state.worldOriginY = 0;
    }

    function fit(bounds, viewportW, viewportH, padding) {
      var plan = computeFit(bounds, viewportW, viewportH, padding);
      state.zoom = plan.zoom;
      state.panX = plan.panX;
      state.panY = plan.panY;
      state.worldOriginX = 0;
      state.worldOriginY = 0;
      if (diagEnabled) {
        try {
          console.info("[WEOS:viewport]", plan);
        } catch (e) {}
      }
      return state.zoom;
    }

    /** Preserve world center when stage size changes (panel toggle). Does not reset zoom. */
    function preserveCenterOnResize(oldW, oldH, newW, newH) {
      var ow = Math.max(1, safeNum(oldW, 1));
      var oh = Math.max(1, safeNum(oldH, 1));
      var nw = Math.max(1, safeNum(newW, 1));
      var nh = Math.max(1, safeNum(newH, 1));
      var z = state.zoom || 1;
      if (!isFinite(z) || z <= 0) z = 1;
      var cx = (ow / 2 - state.panX) / z + state.worldOriginX;
      var cy = (oh / 2 - state.panY) / z + state.worldOriginY;
      state.panX = nw / 2 - (cx - state.worldOriginX) * z;
      state.panY = nh / 2 - (cy - state.worldOriginY) * z;
      if (!isFinite(state.panX)) state.panX = 0;
      if (!isFinite(state.panY)) state.panY = 0;
      return snapshot();
    }

    function applySnapshot(s) {
      if (!s) return;
      if (s.zoom != null) state.zoom = clampZoom(s.zoom);
      if (s.panX != null) state.panX = safeNum(s.panX, 0);
      if (s.panY != null) state.panY = safeNum(s.panY, 0);
      // D3: ignore inherited non-zero worldOrigin from older sessions
      state.worldOriginX = 0;
      state.worldOriginY = 0;
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

    function setDiag(on) {
      diagEnabled = !!on;
    }

    function cssTransform() {
      return "translate(" + state.panX + "px," + state.panY + "px) scale(" + state.zoom + ")";
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
      setDiag: setDiag,
      cssTransform: cssTransform,
      computeFit: computeFit,
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
  global.WEOSCanvas.viewport = {
    create: createViewport,
    clampZoom: clampZoom,
    computeFit: computeFit,
    normalizeBounds: normalizeBounds,
    ZOOM_MIN: DEFAULT_LO,
    ZOOM_MAX: DEFAULT_HI,
    DEFAULT_PAD: DEFAULT_PAD,
  };
})(typeof window !== "undefined" ? window : globalThis);
