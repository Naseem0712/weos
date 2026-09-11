/**
 * WEOS Universal Canvas — Adapter registry (Batch 8).
 * ONE canvas host; product engines via registry (no WindowCanvas/RailingCanvas).
 * Server-side ProductAdapter contract owns calculate/preview; JS mirrors types.
 * D4: normalizeForCanvas strips artificial white page backgrounds for UC only.
 */
(function (global) {
  "use strict";

  /**
   * CANVAS_RENDER: remove full-bleed white page rects so drawings sit on grey/grid.
   * Does not touch glass/panel fills with opacity, stroked profiles, or chips.
   * PDF/PRINT must keep original engine SVG (white paper).
   */
  function normalizeForCanvas(svg) {
    if (!svg || typeof svg !== "string") return svg || "";
    if (svg.indexOf("<svg") < 0) return svg;
    if (/data-weos-canvas-normalized\s*=\s*["']1["']/.test(svg)) return svg;

    var out = svg.replace(
      /<rect\b(?=[^>]*\bfill\s*=\s*["'](?:#fff(?:fff)?|white)["'])(?=[^>]*\bwidth\s*=\s*["']100%["'])(?=[^>]*\bheight\s*=\s*["']100%["'])[^>]*\/?>/gi,
      ""
    );

    function flexNum(n) {
      var f = Number(n);
      if (!isFinite(f)) return String(n).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      var g = String(f);
      var d1 = f.toFixed(1);
      var d0 = String(Math.round(f));
      return "(?:" + g.replace(/\./g, "\\.") + "|" + d1.replace(/\./g, "\\.") + "|" + d0 + ")";
    }

    var vb = out.match(/\bviewBox\s*=\s*["']\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*["']/i);
    var w = null;
    var h = null;
    if (vb) {
      w = vb[3];
      h = vb[4];
    } else {
      var wh = out.match(/<svg\b[^>]*\bwidth\s*=\s*["']([-\d.]+)["'][^>]*\bheight\s*=\s*["']([-\d.]+)["']/i);
      if (wh) {
        w = wh[1];
        h = wh[2];
      }
    }
    if (w != null && h != null) {
      var re = new RegExp(
        "<rect\\b(?=[^>]*\\bfill\\s*=\\s*[\"'](?:#fff(?:fff)?|white)[\"'])" +
          "(?=[^>]*\\bx\\s*=\\s*[\"']0(?:\\.0+)?[\"'])" +
          "(?=[^>]*\\by\\s*=\\s*[\"']0(?:\\.0+)?[\"'])" +
          "(?=[^>]*\\bwidth\\s*=\\s*[\"']" +
          flexNum(w) +
          "[\"'])" +
          "(?=[^>]*\\bheight\\s*=\\s*[\"']" +
          flexNum(h) +
          "[\"'])" +
          "(?![^>]*\\bstroke\\s*=)[^>]*\\/?>",
        "i"
      );
      out = out.replace(re, "");
    }

    out = out.replace(/<svg\b/i, '<svg data-weos-canvas-normalized="1" style="background:transparent"');
    return out;
  }

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
          svg: normalizeForCanvas(svg),
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
      "ACP",
      "HPL",
      "FLUTED",
      "PERFORATED",
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
      normalizeForCanvas: normalizeForCanvas,
    };
  }

  global.WEOSCanvas = global.WEOSCanvas || {};
  global.WEOSCanvas.adapters = {
    createRegistry: createRegistry,
    placeholderSvg: placeholderSvg,
    normalizeForCanvas: normalizeForCanvas,
  };
})(typeof window !== "undefined" ? window : globalThis);
