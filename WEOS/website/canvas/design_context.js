/**
 * WEOS Active Design Context (Canvas D0).
 * ONE owner: selectedProductType → adapter → schema → toolset → renderer.
 * Atomic product switch; renderRevision / AbortController discard stale async;
 * UC ON = route legacy designers into Universal Canvas (no second canvas popup).
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  var UNSUPPORTED_MESSAGE =
    "This product type is not supported on Universal Canvas yet. Window tools are not shown for unsupported products.";

  var TOOLSET_BY_PRODUCT = {
    SLIDING_WINDOW: "sliding",
    CASEMENT_WINDOW: "casement",
    FIXED_WINDOW: "fixed",
    FOLD_WINDOW: "fold",
    DOOR: "door",
    VENTILATOR: "ventilator",
    SHOWER_PARTITION: "shower",
    LOUVER: "louver",
    RAILING: "railing",
    PERGOLA: "pergola",
    GRILL: "grill",
    SURFACE: "surface",
    ACP: "acp",
    HPL: "surface",
    FLUTED: "surface",
    PERFORATED: "surface",
  };

  function normalizeProductType(raw) {
    var key = String(raw || "")
      .trim()
      .toUpperCase();
    if (!key || key === "WINDOW") return "";
    return key;
  }

  function toolsetFor(pt) {
    var key = normalizeProductType(pt);
    if (!key) return "unsupported";
    return TOOLSET_BY_PRODUCT[key] || "unsupported";
  }

  function emptyContext(reason) {
    return {
      selectedProductType: null,
      elementId: null,
      assemblyId: null,
      adapterId: "fallback",
      propertySchema: {
        version: 1,
        groups: [],
        adapterId: "fallback",
        productType: null,
        usedFallback: true,
        toolset: "unsupported",
        guidance: reason || UNSUPPORTED_MESSAGE,
      },
      toolset: "unsupported",
      renderer: "placeholder",
      renderRevision: 0,
      supported: false,
      guidance: reason || UNSUPPORTED_MESSAGE,
      configScope: "none",
      source: "none",
      configPayload: {},
    };
  }

  function createActiveDesignContext(options) {
    options = options || {};
    var state = emptyContext();
    var listeners = [];
    var abortCtrl = null;
    var apiFn = options.api || (typeof global.api === "function" ? global.api : null);

    function snapshot() {
      return {
        selectedProductType: state.selectedProductType,
        elementId: state.elementId,
        assemblyId: state.assemblyId,
        adapterId: state.adapterId,
        propertySchema: state.propertySchema,
        toolset: state.toolset,
        renderer: state.renderer,
        renderRevision: state.renderRevision,
        supported: state.supported,
        guidance: state.guidance,
        configScope: state.configScope,
        source: state.source,
        configPayload: state.configPayload ? Object.assign({}, state.configPayload) : {},
      };
    }

    function emit() {
      var snap = snapshot();
      listeners.forEach(function (fn) {
        try {
          fn(snap);
        } catch (e) {}
      });
      try {
        global.dispatchEvent &&
          global.dispatchEvent(new CustomEvent("weos:design-context", { detail: snap }));
      } catch (e) {}
    }

    function applyServerContext(ctx) {
      if (!ctx || typeof ctx !== "object") return snapshot();
      state.selectedProductType = ctx.selectedProductType || null;
      state.elementId = ctx.elementId || null;
      state.assemblyId = ctx.assemblyId || null;
      state.adapterId = ctx.adapterId || "fallback";
      state.propertySchema = ctx.propertySchema || emptyContext().propertySchema;
      state.toolset = ctx.toolset || "unsupported";
      state.renderer = ctx.renderer || "placeholder";
      state.renderRevision = Number(ctx.renderRevision) || state.renderRevision;
      state.supported = !!ctx.supported;
      state.guidance = ctx.guidance || (state.supported ? null : UNSUPPORTED_MESSAGE);
      state.configScope = ctx.configScope || "none";
      state.source = ctx.source || state.source;
      state.configPayload =
        ctx.configPayload && typeof ctx.configPayload === "object" ? Object.assign({}, ctx.configPayload) : {};
      emit();
      return snapshot();
    }

    function clearTransientDom() {
      // Clear transient preview DOM only — never wipe saved cart/SQL data.
      var live = global.document && global.document.getElementById("livePreview");
      if (live) {
        live.innerHTML = '<span class="muted">Drawing…</span>';
      }
      try {
        if (global.state) {
          global.state._previewLineId = null;
          global.state._previewKey = null;
        }
      } catch (e) {}
      // Drop stale draft chrome that leaks across products (not durable lines).
      try {
        if (global.state) {
          global.state.draftHandleOverrides = {};
          // Do not clear draftCasementPanels when staying in casement — caller decides.
        }
      } catch (e) {}
    }

    function beginRender() {
      if (abortCtrl && typeof abortCtrl.abort === "function") {
        try {
          abortCtrl.abort();
        } catch (e) {}
      }
      abortCtrl =
        typeof AbortController !== "undefined" ? new AbortController() : { aborted: false, abort: function () { this.aborted = true; } };
      state.renderRevision = (Number(state.renderRevision) || 0) + 1;
      var token = {
        revision: state.renderRevision,
        signal: abortCtrl.signal,
        productType: state.selectedProductType,
        elementId: state.elementId,
      };
      return token;
    }

    function isStale(token) {
      if (!token) return true;
      if (token.revision !== state.renderRevision) return true;
      if (token.signal && token.signal.aborted) return true;
      if (token.productType !== state.selectedProductType) return true;
      if ((token.elementId || null) !== (state.elementId || null)) return true;
      return false;
    }

    function commitRender(token, applyFn) {
      if (isStale(token)) return false;
      if (typeof applyFn === "function") applyFn();
      return true;
    }

    function localResolve(productType, elementId, assemblyId, source, configPayload) {
      var pt = normalizeProductType(productType);
      var toolset = toolsetFor(pt);
      var supported = !!pt && toolset !== "unsupported" && !!TOOLSET_BY_PRODUCT[pt];
      // Local optimistic map — server remains authority when API available.
      var adapterGuess = {
        sliding: "window_family",
        casement: "window_family",
        fixed: "window_family",
        fold: "window_family",
        door: "window_family",
        ventilator: "ventilator",
        shower: "shower",
        louver: "louver",
        railing: "railing",
        pergola: "pergola",
        grill: "grill",
        surface: "surface",
        acp: "surface",
        unsupported: "fallback",
      }[toolset];
      state.selectedProductType = pt || null;
      state.elementId = elementId || null;
      state.assemblyId = assemblyId || null;
      state.adapterId = supported ? adapterGuess : "fallback";
      state.toolset = supported ? toolset : "unsupported";
      state.renderer = supported ? (toolset === "pergola" || toolset === "louver" || toolset === "acp" || toolset === "surface" ? "schematic" : "engine") : "placeholder";
      state.supported = supported;
      state.guidance = supported ? null : UNSUPPORTED_MESSAGE;
      state.configScope = elementId ? "element:" + elementId : pt ? "draft:" + pt : "none";
      state.source = source || "local";
      state.configPayload = configPayload && typeof configPayload === "object" ? Object.assign({}, configPayload) : {};
      state.propertySchema = {
        version: 1,
        groups: [],
        adapterId: state.adapterId,
        productType: state.selectedProductType,
        usedFallback: !supported,
        toolset: state.toolset,
        guidance: state.guidance,
      };
      return snapshot();
    }

    function switchProduct(opts) {
      opts = opts || {};
      var prev = snapshot();
      var nextType = opts.productType;
      var sameType =
        normalizeProductType(prev.selectedProductType) &&
        normalizeProductType(prev.selectedProductType) === normalizeProductType(nextType);
      var sameElement = (prev.elementId || null) === (opts.elementId || null);

      // Atomic: abort in-flight renders, clear transient DOM, bump revision.
      beginRender();
      if (!sameType || opts.forceClear) {
        clearTransientDom();
        if (!sameElement || !opts.elementId) {
          state.configPayload = {};
        }
        // Clear specialty mode flags so legacy stacks cannot stick under UC.
        try {
          if (global.state && !sameType) {
            global.state.railingMode = false;
            global.state.showerMode = false;
            global.state.ventMode = false;
            if (normalizeProductType(nextType) !== "CASEMENT_WINDOW") {
              /* leave casement panels only when staying casement */
            }
          }
        } catch (e) {}
      }

      localResolve(
        nextType,
        opts.elementId,
        opts.assemblyId,
        opts.source || "switch",
        sameType && sameElement ? opts.configPayload || state.configPayload : opts.configPayload || null
      );
      state.renderRevision = prev.renderRevision + 1;
      emit();

      // Server authority when available.
      if (apiFn) {
        var revAtRequest = state.renderRevision;
        var body = {
          productType: state.selectedProductType,
          elementId: state.elementId,
          assemblyId: state.assemblyId,
          configPayload: state.configPayload,
          source: opts.source || "switch",
          previous: prev,
        };
        Promise.resolve(apiFn("/api/design-context/switch", { method: "POST", body: body }))
          .then(function (ctx) {
            if (revAtRequest !== state.renderRevision) return; // stale
            applyServerContext(ctx);
            // Keep local revision monotonic if server sent lower.
            if (Number(ctx.renderRevision) < revAtRequest) {
              state.renderRevision = revAtRequest;
            }
            refreshPropertyPanel();
            routeLegacyIntoUc();
          })
          .catch(function () {
            refreshPropertyPanel();
            routeLegacyIntoUc();
          });
      } else {
        refreshPropertyPanel();
        routeLegacyIntoUc();
      }
      return snapshot();
    }

    function selectElement(sel) {
      sel = sel || {};
      return switchProduct({
        productType: sel.productType,
        elementId: sel.elementId || null,
        assemblyId: sel.assemblyId || null,
        configPayload: sel.configPayload || null,
        source: "element",
      });
    }

    function selectCatalogue(meta, world) {
      meta = meta || {};
      var pt =
        meta.elementProductType ||
        meta.canvasProductType ||
        guessCatalogueType(meta, world);
      return switchProduct({
        productType: pt,
        elementId: null,
        assemblyId: null,
        configPayload: null,
        source: "catalogue",
        forceClear: true,
      });
    }

    function guessCatalogueType(meta, world) {
      var blob = [
        meta.productType,
        meta.id,
        meta.category,
        meta.displayName,
        meta.system,
        world,
      ]
        .map(function (x) {
          return String(x || "").toLowerCase();
        })
        .join(" ");
      if (blob.indexOf("pergola") >= 0) return "PERGOLA";
      if (blob.indexOf("ventilat") >= 0) return "VENTILATOR";
      if (blob.indexOf("shower") >= 0) return "SHOWER_PARTITION";
      if (blob.indexOf("louver") >= 0 || blob.indexOf("louvre") >= 0) return "LOUVER";
      if (blob.indexOf("rail") >= 0) return "RAILING";
      if (blob.indexOf("casement") >= 0 || blob.indexOf("openable") >= 0) return "CASEMENT_WINDOW";
      if (blob.indexOf("fold") >= 0 || blob.indexOf("bifold") >= 0) return "FOLD_WINDOW";
      if (/\bacp\b/.test(blob)) return "ACP";
      if (/(hpl|fluted|perforated|cladding|facade)/.test(blob)) return "SURFACE";
      if (blob.indexOf("fixed") >= 0 || blob.indexOf("grid") >= 0) return "FIXED_WINDOW";
      if (blob.indexOf("door") >= 0 && blob.indexOf("window") < 0) return "DOOR";
      if (/(slid|tele|sync|window)/.test(blob)) return "SLIDING_WINDOW";
      var w = String(world || "").toLowerCase();
      var map = {
        sliding: "SLIDING_WINDOW",
        casement: "CASEMENT_WINDOW",
        fixed: "FIXED_WINDOW",
        fold: "FOLD_WINDOW",
        bifold: "FOLD_WINDOW",
        door: "DOOR",
        ventilator: "VENTILATOR",
        shower: "SHOWER_PARTITION",
        louver: "LOUVER",
        railing: "RAILING",
        staircase_railing: "RAILING",
        pergola: "PERGOLA",
        surface: "SURFACE",
        acp: "ACP",
      };
      return map[w] || "";
    }

    function refreshPropertyPanel() {
      try {
        var panel = global.WEOS_PROPERTY_PANEL;
        if (!panel) return;
        var localEl =
          state.elementId && String(state.elementId).indexOf("local-") === 0;
        // Local UC drafts (D1 Add Design) paint from ActiveDesignContext schema — no SQL id yet.
        if (localEl || !state.elementId) {
          if (typeof panel.renderPanel === "function") {
            if (!state.supported) {
              panel.renderPanel({
                kind: "none",
                guidance: state.guidance || UNSUPPORTED_MESSAGE,
                schema: state.propertySchema,
                values: { unsupportedNotice: state.guidance || UNSUPPORTED_MESSAGE },
                selection: {
                  kind: "none",
                  productType: state.selectedProductType,
                  elementId: state.elementId || null,
                },
              });
              return;
            }
            panel.renderPanel({
              kind: "element",
              schema: state.propertySchema,
              values: Object.assign(
                {
                  productType: state.selectedProductType,
                  widthMm: state.configPayload && state.configPayload.widthMm,
                  heightMm: state.configPayload && state.configPayload.heightMm,
                },
                state.configPayload || {}
              ),
              selection: {
                kind: localEl ? "element" : "catalogue",
                productType: state.selectedProductType,
                elementId: state.elementId || null,
                assemblyId: state.assemblyId || null,
              },
            });
          }
          return;
        }
        if (state.elementId && typeof panel.loadSelection === "function") {
          panel.loadSelection({
            elementId: state.elementId,
            assemblyId: state.assemblyId,
            productType: state.selectedProductType,
          });
          return;
        }
        // Catalogue / draft mode: paint schema from ActiveDesignContext (no element yet).
        if (typeof panel.renderPanel === "function") {
          if (!state.supported) {
            panel.renderPanel({
              kind: "none",
              guidance: state.guidance || UNSUPPORTED_MESSAGE,
              schema: state.propertySchema,
              values: { unsupportedNotice: state.guidance || UNSUPPORTED_MESSAGE },
              selection: {
                kind: "none",
                productType: state.selectedProductType,
                elementId: null,
              },
            });
            return;
          }
          panel.renderPanel({
            kind: "element",
            schema: state.propertySchema,
            values: Object.assign(
              { productType: state.selectedProductType },
              state.configPayload || {}
            ),
            selection: {
              kind: "catalogue",
              productType: state.selectedProductType,
              elementId: null,
              assemblyId: null,
            },
          });
        }
      } catch (e) {}
    }

    function routeLegacyIntoUc() {
      if (!global.WEOS_UNIVERSAL_CANVAS) return;
      // Ensure legacy tool stacks stay wrapped; never open a second canvas host.
      try {
        if (C.propertyPanel && C.propertyPanel.hideLegacyTools) {
          C.propertyPanel.hideLegacyTools(true);
        }
      } catch (e) {}
      var hosts = global.document
        ? global.document.querySelectorAll("#universalCanvasHost, .uc-host")
        : [];
      if (hosts.length > 1) {
        // Keep the first UC host; remove accidental duplicates (second canvas NOT OK).
        for (var i = 1; i < hosts.length; i++) {
          try {
            hosts[i].parentNode && hosts[i].parentNode.removeChild(hosts[i]);
          } catch (e2) {}
        }
      }
      // Config modals remain OK — only block product-specific canvas popups.
      try {
        global.document.querySelectorAll("[data-product-canvas-popup]").forEach(function (node) {
          node.setAttribute("data-uc-routed", "1");
          node.style.display = "none";
        });
      } catch (e3) {}
    }

    function onChange(fn) {
      if (typeof fn === "function") listeners.push(fn);
      return function () {
        listeners = listeners.filter(function (x) {
          return x !== fn;
        });
      };
    }

    return {
      get: snapshot,
      switchProduct: switchProduct,
      selectElement: selectElement,
      selectCatalogue: selectCatalogue,
      beginRender: beginRender,
      isStale: isStale,
      commitRender: commitRender,
      clearTransientDom: clearTransientDom,
      routeLegacyIntoUc: routeLegacyIntoUc,
      refreshPropertyPanel: refreshPropertyPanel,
      onChange: onChange,
      applyServerContext: applyServerContext,
      toolsetFor: toolsetFor,
      normalizeProductType: normalizeProductType,
      UNSUPPORTED_MESSAGE: UNSUPPORTED_MESSAGE,
    };
  }

  var singleton = null;

  function getActive(options) {
    if (!singleton) singleton = createActiveDesignContext(options || {});
    return singleton;
  }

  C.designContext = {
    create: createActiveDesignContext,
    getActive: getActive,
    toolsetFor: toolsetFor,
    normalizeProductType: normalizeProductType,
    UNSUPPORTED_MESSAGE: UNSUPPORTED_MESSAGE,
  };
})(typeof window !== "undefined" ? window : globalThis);
