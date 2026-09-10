/**
 * WEOS Universal Engineering Canvas Host — ONE canvas for all products.
 * Feature flag: WEOS_UNIVERSAL_CANVAS (env /api/flags or ?universalCanvas=1).
 * Does not rewrite product engines; preview SVG via adapters; drag deferred.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  function qsFlag() {
    try {
      var u = new URL(global.location.href);
      var v = u.searchParams.get("universalCanvas");
      if (v != null) return /^(1|true|yes|on)$/i.test(v);
    } catch (e) {}
    return null;
  }

  function isEnabled(serverFlag) {
    if (typeof global.WEOS_UNIVERSAL_CANVAS === "boolean") return global.WEOS_UNIVERSAL_CANVAS;
    var q = qsFlag();
    if (q != null) return q;
    if (typeof serverFlag === "boolean") return serverFlag;
    return false;
  }

  function createHost(rootEl, options) {
    options = options || {};
    if (!rootEl) throw new Error("UniversalCanvas root required");
    if (!C.viewport || !C.selection || !C.adapters || !C.sceneRenderer) {
      throw new Error("WEOSCanvas modules missing — load viewport/selection/adapters/scene_renderer first");
    }

    var viewport = C.viewport.create();
    var selection = C.selection.create({ allowMulti: false });
    var registry = C.adapters.createRegistry();
    var model = {
      elements: [],
      connections: [],
      bounds: C.sceneRenderer.boundsFor([]),
      floors: [],
      filterFloorId: null,
      filterLocationId: null,
      previewContext: { previewByElementId: {} },
      scene: null,
      selectedSync: null,
    };
    var panning = null;
    var onSelectCbs = [];

    rootEl.classList.add("uc-host");
    rootEl.innerHTML =
      '<div class="uc-toolbar" style="display:flex;gap:.35rem;align-items:center;flex-wrap:wrap;margin-bottom:.4rem">' +
      '<strong style="margin-right:.4rem">Engineering Canvas</strong>' +
      '<label class="muted" style="font-size:.78rem">Floor <select id="ucFloorSel"></select></label>' +
      '<label class="muted" style="font-size:.78rem">Location <select id="ucLocSel"></select></label>' +
      '<span style="flex:1"></span>' +
      '<button type="button" class="btn ghost sm" data-uc="fit">Fit</button>' +
      '<button type="button" class="btn ghost sm" data-uc="zoomOut">−</button>' +
      '<span class="muted uc-zoom-label" style="min-width:3.2rem;text-align:center;font-size:.78rem">100%</span>' +
      '<button type="button" class="btn ghost sm" data-uc="zoomIn">+</button>' +
      '<button type="button" class="btn ghost sm" data-uc="reset">Reset</button>' +
      "</div>" +
      '<div class="uc-viewport" tabindex="0" style="position:relative;flex:1 1 auto;min-height:0;height:100%;' +
      "overflow:hidden;background:#d8dee6;border:1px solid rgba(0,0,0,.12);border-radius:12px;cursor:grab\">" +
      "</div>" +
      '<div class="uc-selinfo muted" style="margin-top:.35rem;font-size:.78rem">No selection</div>';

    var vpEl = rootEl.querySelector(".uc-viewport");
    var zoomLabel = rootEl.querySelector(".uc-zoom-label");
    var selInfo = rootEl.querySelector(".uc-selinfo");
    var floorSel = rootEl.querySelector("#ucFloorSel");
    var locSel = rootEl.querySelector("#ucLocSel");

    function updateZoomLabel() {
      if (zoomLabel) zoomLabel.textContent = Math.round(viewport.zoom * 100) + "%";
    }

    function paint() {
      C.sceneRenderer.renderInto(vpEl, model, viewport, selection, registry);
      updateZoomLabel();
      var snap = selection.snapshot();
      var el = model.elements.filter(function (e) {
        return e.elementId === snap.primaryElementId;
      })[0];
      model.selectedSync = el
        ? {
            elementId: el.elementId,
            productType: el.productType,
            widthMm: el.widthMm,
            heightMm: el.heightMm,
            displayCode: el.displayCode,
            assemblyId: el.assemblyId,
            floorId: el.floorId,
            locationId: el.locationId,
          }
        : null;
      if (selInfo) {
        selInfo.textContent = el
          ? el.displayCode +
            " · " +
            el.productType +
            " · " +
            el.widthMm +
            "×" +
            el.heightMm +
            " mm · " +
            (el.floorName || el.floorId || "—") +
            " / " +
            (el.locationName || el.locationId || "—")
          : "No selection";
      }
    }

    function applyFilters() {
      var all = C.sceneRenderer.flattenElements(model.scene || { floors: [], unlocatedAssemblies: [] });
      var conns = C.sceneRenderer.flattenConnections(model.scene || {});
      if (model.filterFloorId) {
        all = all.filter(function (e) {
          return e.floorId === model.filterFloorId;
        });
      }
      if (model.filterLocationId) {
        all = all.filter(function (e) {
          return e.locationId === model.filterLocationId;
        });
      }
      model.elements = all;
      model.connections = conns.filter(function (c) {
        var ids = Object.create(null);
        all.forEach(function (e) {
          ids[e.elementId] = true;
        });
        return ids[c.elementAId] && ids[c.elementBId];
      });
      model.bounds = C.sceneRenderer.boundsFor(all);
      paint();
    }

    function fillSelectors() {
      var floors = (model.scene && model.scene.floors) || [];
      floorSel.innerHTML = '<option value="">All floors</option>';
      floors.forEach(function (fl) {
        floorSel.innerHTML +=
          '<option value="' +
          String(fl.floorId || "").replace(/"/g, "") +
          '">' +
          String(fl.name || fl.code || fl.floorId).replace(/</g, "") +
          "</option>";
      });
      floorSel.value = model.filterFloorId || "";
      refillLocations();
    }

    function refillLocations() {
      var floors = (model.scene && model.scene.floors) || [];
      locSel.innerHTML = '<option value="">All locations</option>';
      floors.forEach(function (fl) {
        if (model.filterFloorId && fl.floorId !== model.filterFloorId) return;
        (fl.locations || []).forEach(function (loc) {
          locSel.innerHTML +=
            '<option value="' +
            String(loc.locationId || "").replace(/"/g, "") +
            '">' +
            String(loc.name || loc.code || loc.locationId).replace(/</g, "") +
            "</option>";
        });
      });
      locSel.value = model.filterLocationId || "";
    }

    function loadScene(scene) {
      model.scene = scene || { floors: [], unlocatedAssemblies: [] };
      model.floors = model.scene.floors || [];
      fillSelectors();
      applyFilters();
      fit();
      return getViewModel();
    }

    function fit() {
      var rect = vpEl.getBoundingClientRect();
      viewport.fit(model.bounds, rect.width || 800, rect.height || 600, 48);
      paint();
    }

    function resetView() {
      viewport.reset();
      paint();
    }

    function zoomIn() {
      var rect = vpEl.getBoundingClientRect();
      viewport.zoomBy(1.15, { x: rect.width / 2, y: rect.height / 2 });
      paint();
    }

    function zoomOut() {
      var rect = vpEl.getBoundingClientRect();
      viewport.zoomBy(1 / 1.15, { x: rect.width / 2, y: rect.height / 2 });
      paint();
    }

    function setElementPreviewSvg(elementId, svg) {
      model.previewContext.previewByElementId[elementId] = svg;
      paint();
    }

    function getViewModel() {
      return {
        host: "UniversalCanvas",
        elements: model.elements,
        connections: model.connections,
        bounds: model.bounds,
        selection: selection.snapshot(),
        selected: model.selectedSync,
        viewport: viewport.snapshot(),
        filterFloorId: model.filterFloorId,
        filterLocationId: model.filterLocationId,
        elementDragEnabled: false,
      };
    }

    function getSelectedDims() {
      var s = model.selectedSync;
      if (!s) return null;
      return { widthMm: s.widthMm, heightMm: s.heightMm, elementId: s.elementId };
    }

    rootEl.querySelector('[data-uc="fit"]').onclick = fit;
    rootEl.querySelector('[data-uc="zoomIn"]').onclick = zoomIn;
    rootEl.querySelector('[data-uc="zoomOut"]').onclick = zoomOut;
    rootEl.querySelector('[data-uc="reset"]').onclick = resetView;

    floorSel.onchange = function () {
      model.filterFloorId = floorSel.value || null;
      model.filterLocationId = null;
      refillLocations();
      applyFilters();
      fit();
    };
    locSel.onchange = function () {
      model.filterLocationId = locSel.value || null;
      applyFilters();
      fit();
    };

    selection.onChange(function (snap) {
      paint();
      onSelectCbs.forEach(function (fn) {
        try {
          fn(model.selectedSync, snap);
        } catch (e) {}
      });
    });

    vpEl.addEventListener(
      "wheel",
      function (ev) {
        ev.preventDefault();
        var rect = vpEl.getBoundingClientRect();
        var factor = ev.deltaY < 0 ? 1.1 : 1 / 1.1;
        viewport.zoomBy(factor, { x: ev.clientX - rect.left, y: ev.clientY - rect.top });
        paint();
      },
      { passive: false }
    );

    vpEl.addEventListener("pointerdown", function (ev) {
      var t = ev.target;
      var elNode = t && t.closest ? t.closest("[data-element-id]") : null;
      if (elNode) {
        selection.select(elNode.getAttribute("data-element-id"));
        return;
      }
      // Background / middle-button pan — never moves elements.
      if (ev.button === 0 || ev.button === 1) {
        panning = { x: ev.clientX, y: ev.clientY, pointerId: ev.pointerId };
        try {
          vpEl.setPointerCapture(ev.pointerId);
        } catch (e) {}
        vpEl.style.cursor = "grabbing";
        selection.clear();
      }
    });

    vpEl.addEventListener("pointermove", function (ev) {
      if (!panning) return;
      viewport.panBy(ev.clientX - panning.x, ev.clientY - panning.y);
      panning.x = ev.clientX;
      panning.y = ev.clientY;
      paint();
    });

    function endPan(ev) {
      if (!panning) return;
      panning = null;
      vpEl.style.cursor = "grab";
      try {
        if (ev && ev.pointerId != null) vpEl.releasePointerCapture(ev.pointerId);
      } catch (e) {}
    }
    vpEl.addEventListener("pointerup", endPan);
    vpEl.addEventListener("pointercancel", endPan);

    return {
      loadScene: loadScene,
      fit: fit,
      resetView: resetView,
      zoomIn: zoomIn,
      zoomOut: zoomOut,
      setElementPreviewSvg: setElementPreviewSvg,
      getViewModel: getViewModel,
      getSelectedDims: getSelectedDims,
      selection: selection,
      viewport: viewport,
      registry: registry,
      onSelect: function (fn) {
        if (typeof fn === "function") onSelectCbs.push(fn);
      },
      paint: paint,
      isUniversalCanvas: true,
    };
  }

  /**
   * Progressive SPA mount: wrap #livePreview when flag on; leave forms alone.
   */
  function tryMount(options) {
    options = options || {};
    if (!isEnabled(options.serverEnabled)) return null;
    var live = global.document && global.document.getElementById("livePreview");
    if (!live) return null;
    var panel = live.closest(".cart-preview") || live.parentElement;
    if (!panel) return null;

    // D0: ONE Universal Canvas only — never mount a second host.
    var existing = global.document.getElementById("universalCanvasHost");
    if (existing && global.WEOS_UNIVERSAL_CANVAS_HOST && global.WEOS_UNIVERSAL_CANVAS_HOST.isUniversalCanvas) {
      return global.WEOS_UNIVERSAL_CANVAS_HOST;
    }

    var mount = existing;
    if (!mount) {
      mount = global.document.createElement("div");
      mount.id = "universalCanvasHost";
      mount.className = "uc-mount";
      mount.style.cssText =
        "display:flex;flex-direction:column;flex:1 1 auto;min-height:0;height:clamp(520px,72vh,880px)";
      live.style.display = "none";
      live.setAttribute("data-uc-compat", "1");
      panel.insertBefore(mount, live);
    }
    panel.classList.add("uc-active");
    var host = createHost(mount, options);
    global.WEOS_UNIVERSAL_CANVAS_HOST = host;

    // Compatibility: keep zoom buttons wired.
    var fitBtn = global.document.getElementById("btnPrevFit");
    var zin = global.document.getElementById("btnPrevZoomIn");
    var zout = global.document.getElementById("btnPrevZoomOut");
    if (fitBtn) fitBtn.onclick = function () {
      host.fit();
    };
    if (zin) zin.onclick = function () {
      host.zoomIn();
    };
    if (zout) zout.onclick = function () {
      host.zoomOut();
    };

    try {
      if (C.designContext && C.designContext.getActive) {
        C.designContext.getActive().routeLegacyIntoUc();
      }
    } catch (e) {}

    return host;
  }

  C.UniversalCanvas = {
    create: createHost,
    tryMount: tryMount,
    isEnabled: isEnabled,
  };
  C.create = createHost;
})(typeof window !== "undefined" ? window : globalThis);
