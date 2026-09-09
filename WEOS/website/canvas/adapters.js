/**
 * WEOS Universal Canvas — Adapter registry (Batch 8).
 * ONE canvas host; product engines via registry (no WindowCanvas/RailingCanvas).
 * Server-side ProductAdapter contract owns calculate/preview; JS mirrors types.
 */
(function (global) {
  "use strict";

  function placeholderSvg(el) {
    var w = Math.max(1, Number(el.widthMm) || 100);
    var h = Math.max(1, Number(el.heightMm) || 100);
    var code = el.displayCode || el.elementId || "?";
    var pt = el.productType || "OTHER";
    return (
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' +
      w +
      " " +
      h +
      '" data-weos-placeholder="1">' +
      '<rect x="0" y="0" width="' +
      w +
      '" height="' +
      h +
      '" fill="#e8eef4" stroke="#4a5a6a" stroke-width="8"/>' +
      '<text x="' +
      w / 2 +
      '" y="' +
      h / 2 +
      '" text-anchor="middle" dominant-baseline="middle" ' +
      'font-family="Segoe UI,sans-serif" font-size="' +
      Math.max(48, Math.min(w, h) / 8) +
      '" fill="#334455">' +
      String(code).replace(/</g, "") +
      "</text>" +
      '<title>' +
      String(code).replace(/</g, "") +
      " " +
      String(pt).replace(/</g, "") +
      " " +
      w +
      "×" +
      h +
      "</title>" +
      "</svg>"
    );
  }

  function createRegistry() {
    var map = Object.create(null);

    function register(productType, fn) {
      var key = String(productType || "")
        .trim()
        .toUpperCase();
      if (!key) throw new Error("productType required");
      if (key === "WINDOW") throw new Error("Do not register collapsed WINDOW — use SLIDING_WINDOW / …");
      map[key] = fn;
    }

    function lookup(productType) {
      var key = String(productType || "")
        .trim()
        .toUpperCase();
      return map[key] || null;
    }

    function render(el, context) {
      context = context || {};
      var fn = lookup(el.productType);
      var usedFallback = !fn;
      var out;
      if (fn) {
        try {
          out = fn(el, context);
        } catch (e) {
          out = null;
          usedFallback = true;
        }
      }
      if (!out || !out.svg) {
        out = {
          kind: "placeholder",
          svg: placeholderSvg(el),
          elementId: el.elementId,
          productType: el.productType,
          widthMm: el.widthMm,
          heightMm: el.heightMm,
          displayCode: el.displayCode,
        };
        usedFallback = true;
      }
      out.usedFallback = usedFallback;
      return out;
    }

    function registeredTypes() {
      return Object.keys(map).sort();
    }

    // Prefer engine SVG from server canvas view / preview API; else placeholder.
    function previewSvgAdapter(el, context) {
      var svg =
        (context && context.previewSvg) ||
        el.previewSvg ||
        (el.render && el.render.svg) ||
        (context && context.previewByElementId && context.previewByElementId[el.elementId]);
      if (svg) {
        return {
          kind: "preview_svg",
          svg: svg,
          elementId: el.elementId,
          productType: el.productType,
          widthMm: el.widthMm,
          heightMm: el.heightMm,
          displayCode: el.displayCode,
        };
      }
      return {
        kind: "placeholder",
        svg: placeholderSvg(el),
        elementId: el.elementId,
        productType: el.productType,
        widthMm: el.widthMm,
        heightMm: el.heightMm,
        displayCode: el.displayCode,
      };
    }

    [
      "SLIDING_WINDOW",
      "CASEMENT_WINDOW",
      "FIXED_WINDOW",
      "FOLD_WINDOW",
      "DOOR",
      "VENTILATOR",
      "SHOWER_PARTITION",
      "RAILING",
      "GRILL",
      "PERGOLA",
      "LOUVER",
      "SURFACE",
    ].forEach(function (pt) {
      register(pt, previewSvgAdapter);
    });

    return {
      register: register,
      lookup: lookup,
      render: render,
      registeredTypes: registeredTypes,
      placeholderSvg: placeholderSvg,
      previewSvgAdapter: previewSvgAdapter,
    };
  }

  global.WEOSCanvas = global.WEOSCanvas || {};
  global.WEOSCanvas.adapters = { createRegistry: createRegistry, placeholderSvg: placeholderSvg };
})(typeof window !== "undefined" ? window : globalThis);
