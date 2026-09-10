/**
 * WEOS Universal Engineering Canvas Host — ONE canvas for all products.
 * Batch D/D1/D2 workspace chrome; Canvas D3 viewport stability.
 * Feature flag: WEOS_UNIVERSAL_CANVAS (env /api/flags).
 * Canvas D1: default ON. Rollback: ?universalCanvas=0 or WEOS_UNIVERSAL_CANVAS=0.
 * Does not rewrite product engines; preview SVG via adapters; Member/Grid deferred to E.
 *
 * Fit priority (D3):
 *   1) Fit Selected — Fit button / F when a selection exists (engineering mm bounds)
 *   2) Fit Scene — loadScene, Reset View, floor/location filters, empty selection
 *   3) Initial open / first async preview resolve — Fit ONCE (not every property change)
 * Never Fit from SVG viewBox units — artwork is stretched into widthMm×heightMm.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  /**
   * Feature flag: WEOS_UNIVERSAL_CANVAS (env /api/flags).
   * Canvas D1: default ON. Explicit rollback: ?universalCanvas=0 or env=0.
   */
  function qsFlag() {
    try {
      var u = new URL(global.location.href);
      if (!u.searchParams.has("universalCanvas")) return null;
      var v = String(u.searchParams.get("universalCanvas") || "").trim();
      if (/^(0|false|no|off)$/i.test(v)) return false;
      if (/^(1|true|yes|on)$/i.test(v)) return true;
      return null;
    } catch (e) {}
    return null;
  }

  function isEnabled(serverFlag) {
    var q = qsFlag();
    if (q != null) return q;
    if (typeof serverFlag === "boolean") return serverFlag;
    if (typeof global.WEOS_UNIVERSAL_CANVAS === "boolean") return global.WEOS_UNIVERSAL_CANVAS;
    // D1: if flags fetch failed and no query override, prefer ON.
    return true;
  }

  function createHost(rootEl, options) {
    options = options || {};
    if (!rootEl) throw new Error("UniversalCanvas root required");
    if (!C.viewport || !C.selection || !C.adapters || !C.sceneRenderer) {
      throw new Error("WEOSCanvas modules missing — load viewport/selection/adapters/scene_renderer first");
    }
    if (!C.workspace || !C.commands || !C.grid || !C.snap || !C.dimensions) {
      throw new Error("WEOSCanvas Batch D modules missing — load commands/grid/snap/dimensions/workspace first");
    }

    var shell = C.workspace.mountShell(rootEl);
    var vpEl = shell.viewport;
    var viewport = C.viewport.create();
    var selection = C.selection.create({ allowMulti: true });
    var registry = C.adapters.createRegistry();
    var history = C.commands.createHistory({ maxSize: 50 });
    var grid = C.grid.create({ visible: true });
    var snap = C.snap.create({ enabled: true });
    var cmdState = C.commands.createCommandState({
      activeTool: C.commands.TOOLS.SELECT,
      gridVisible: true,
      snapEnabled: true,
    });

    var model = {
      elements: [],
      localElements: [],
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
    var lastVpSize = { w: 0, h: 0 };
    var onSelectCbs = [];
    var onCommandCbs = [];
    /** Per-design viewport snapshots — switching W-01 → P-01 must not inherit nonsense zoom. */
    var viewByDesignId = Object.create(null);
    var activeDesignId = null;
    /** elementId → true: Fit once when first real adapter SVG arrives (not placeholder). */
    var pendingPreviewFit = Object.create(null);
    var initialSceneFitDone = false;
    try {
      var _diagQs = new URL(global.location.href).searchParams.get("ucViewportDiag");
      if (_diagQs && /^(1|true|yes|on)$/i.test(_diagQs) && viewport.setDiag) viewport.setDiag(true);
    } catch (eDiag) {}

    var zoomLabel = rootEl.querySelector('[data-uc="zoomLabel"]');
    var designLabel = rootEl.querySelector('[data-uc="designLabel"]');
    var selInfo = rootEl.querySelector('[data-uc="selinfo"]');
    var cursorStatus = rootEl.querySelector('[data-uc="cursorStatus"]');
    var savePill = rootEl.querySelector('[data-uc="saveStatus"]');
    var floorSel = rootEl.querySelector("#ucFloorSel");
    var locSel = rootEl.querySelector("#ucLocSel");
    var undoBtn = rootEl.querySelector('[data-uc="undo"]');
    var redoBtn = rootEl.querySelector('[data-uc="redo"]');
    var deleteBtn = rootEl.querySelector('[data-uc="delete"]');
    var gridBtn = rootEl.querySelector('[data-uc="gridToggle"]');
    var snapBtn = rootEl.querySelector('[data-uc="snapToggle"]');

    function emitCommand() {
      var snapCmd = getCommandState();
      onCommandCbs.forEach(function (fn) {
        try {
          fn(snapCmd);
        } catch (e) {}
      });
    }

    function getCommandState() {
      var hs = (history && typeof history.snapshot === "function") ? history.snapshot() : {};
      cmdState.canUndo = !!hs.canUndo;
      cmdState.canRedo = !!hs.canRedo;
      cmdState.zoom = viewport.zoom;
      cmdState.gridVisible = grid.visible;
      cmdState.snapEnabled = snap.enabled;
      var sel =
        selection && typeof selection.snapshot === "function" ? selection.snapshot() : {};
      var ids = Array.isArray(sel.selectedIds)
        ? sel.selectedIds
        : Array.isArray(sel.selectedElementIds)
          ? sel.selectedElementIds
          : [];
      cmdState.selection = {
        selectedIds: ids.slice(),
        primaryId: sel.primaryId || sel.primaryElementId || (ids.length ? ids[0] : null),
        kind: sel.kind || (ids.length ? "element" : "none"),
      };
      return JSON.parse(JSON.stringify(cmdState));
    }

    function syncChrome() {
      C.workspace.syncToolRail(shell.toolRail, cmdState.activeTool);
      vpEl.setAttribute("data-tool", cmdState.activeTool);
      if (undoBtn) undoBtn.disabled = !history.canUndo;
      if (redoBtn) redoBtn.disabled = !history.canRedo;
      if (deleteBtn) {
        deleteBtn.disabled = true;
        deleteBtn.title = "Delete unavailable — no safe backend delete in Batch D";
      }
      if (gridBtn) gridBtn.classList.toggle("is-active", grid.visible);
      if (snapBtn) snapBtn.classList.toggle("is-active", snap.enabled);
      C.workspace.syncSavePill(savePill, cmdState.saveStatus);
      try {
        emitCommand();
      } catch (eEmit) {}
    }

    function updateZoomLabel() {
      if (zoomLabel) zoomLabel.textContent = Math.round(viewport.zoom * 100) + "%";
      updateCursorStatus();
    }

    function updateCursorStatus(world) {
      if (!cursorStatus) return;
      var x = world && world.xMm != null ? Math.round(world.xMm) : "—";
      var y = world && world.yMm != null ? Math.round(world.yMm) : "—";
      cursorStatus.textContent =
        "X " + x + " mm · Y " + y + " mm · Zoom " + Math.round(viewport.zoom * 100) + "%";
      cmdState.cursor = {
        xMm: world && world.xMm != null ? world.xMm : null,
        yMm: world && world.yMm != null ? world.yMm : null,
      };
    }

    function paint() {
      var showDims =
        cmdState.activeTool === C.commands.TOOLS.MEASURE ||
        !!(selection.snapshot().primaryId);
      C.sceneRenderer.renderInto(vpEl, model, viewport, selection, registry, {
        grid: grid,
        dimensions: C.dimensions,
        showDimensions: showDims,
      });
      updateZoomLabel();
      var snapSel = selection.snapshot();
      var el = model.elements.filter(function (e) {
        return e.elementId === snapSel.primaryElementId;
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
        if (el) {
          selInfo.textContent =
            el.displayCode +
            " · " +
            el.productType +
            " · " +
            el.widthMm +
            "×" +
            el.heightMm +
            " mm · " +
            (el.floorName || el.floorId || "—") +
            " / " +
            (el.locationName || el.locationId || "—");
        } else {
          selInfo.textContent = "No selection";
        }
      }
      if (designLabel) {
        if (el) {
          designLabel.textContent =
            String(el.displayCode || el.elementId || "") +
            (el.productType ? " · " + String(el.productType).replace(/_/g, " ") : "");
        } else {
          designLabel.textContent = "Design";
        }
      }
      try {
        var extTitle = global.document && global.document.getElementById("ucSelectionTitle");
        if (extTitle) {
          extTitle.textContent = el
            ? String(el.displayCode || el.elementId) +
              " · " +
              String(el.productType || "").replace(/_/g, " ")
            : "No selection";
        }
        var pageTitle = global.document && global.document.getElementById("title");
        if (pageTitle && global.document.getElementById("view-cart") &&
            !global.document.getElementById("view-cart").classList.contains("hidden") &&
            global.WEOS_UNIVERSAL_CANVAS) {
          pageTitle.textContent = el
            ? String(el.displayCode || "Design") + " · Engineering Workspace"
            : "Engineering Workspace";
        }
      } catch (eTitle) {}
      syncChrome();
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
      model.elements = all.concat(model.localElements || []);
      model.connections = conns.filter(function (c) {
        var ids = Object.create(null);
        model.elements.forEach(function (e) {
          ids[e.elementId] = true;
        });
        return ids[c.elementAId] && ids[c.elementBId];
      });
      model.bounds = C.sceneRenderer.boundsFor(model.elements);
      paint();
    }

    function upsertLocalElement(el) {
      if (!el || !el.elementId) return null;
      // Deterministic world placement near origin (engineering mm — never CSS/legacy coords).
      var xMm = el.xMm != null ? Number(el.xMm) : 0;
      var yMm = el.yMm != null ? Number(el.yMm) : 0;
      if (!isFinite(xMm)) xMm = 0;
      if (!isFinite(yMm)) yMm = 0;
      var next = {
        elementId: String(el.elementId),
        displayCode: el.displayCode || el.elementId,
        productType: el.productType || "OTHER",
        productId: el.productId || null,
        widthMm: Number(el.widthMm) || 1200,
        heightMm: Number(el.heightMm) || 1200,
        xMm: xMm,
        yMm: yMm,
        orientation: el.orientation || "elevation",
        assemblyId: el.assemblyId || null,
        floorId: el.floorId || null,
        locationId: el.locationId || null,
        configPayload: el.configPayload || {},
        geometryPayload: el.geometryPayload || {},
        status: el.status || "draft",
        local: true,
      };
      var found = false;
      model.localElements = (model.localElements || []).map(function (e) {
        if (e.elementId === next.elementId) {
          found = true;
          return Object.assign({}, e, next);
        }
        return e;
      });
      if (!found) {
        model.localElements.push(next);
      }
      applyFilters();
      return next;
    }

    function selectElementById(elementId, opts) {
      opts = opts || {};
      if (!elementId) {
        persistActiveView();
        activeDesignId = null;
        selection.clear();
        paint();
        onSelectCbs.forEach(function (fn) {
          try {
            fn(null);
          } catch (e) {}
        });
        return null;
      }
      persistActiveView();
      selection.select(elementId, false, "element");
      var restored = restoreViewFor(elementId);
      activeDesignId = String(elementId);
      paint();
      var el = model.elements.filter(function (e) {
        return e.elementId === elementId;
      })[0];
      // Restore per-design view when available; otherwise fit (unless caller opts out).
      if (opts.fit === true || (opts.fit !== false && !restored)) {
        fitSelected();
      }
      onSelectCbs.forEach(function (fn) {
        try {
          fn(el || { elementId: elementId });
        } catch (e) {}
      });
      return el || null;
    }

    function fillSelectors() {
      if (!floorSel) return;
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
      if (!locSel) return;
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
      initialSceneFitDone = false;
      fitScene();
      initialSceneFitDone = true;
      return getViewModel();
    }

    function persistActiveView() {
      if (!activeDesignId) return;
      try {
        viewByDesignId[activeDesignId] = viewport.snapshot();
      } catch (e) {}
    }

    function restoreViewFor(designId) {
      if (!designId) return false;
      var snap = viewByDesignId[designId];
      if (!snap) return false;
      var z = Number(snap.zoom);
      if (!isFinite(z) || z < 0.15 || z > 6) return false;
      viewport.applySnapshot(snap);
      return true;
    }

    function markPendingPreviewFit(elementId) {
      if (elementId) pendingPreviewFit[String(elementId)] = true;
    }

    function elementBounds(el) {
      if (!el) return null;
      var w = Number(el.widthMm);
      var h = Number(el.heightMm);
      if (!(w > 0) || !(h > 0) || !isFinite(w) || !isFinite(h)) return null;
      var x = Number(el.xMm) || 0;
      var y = Number(el.yMm) || 0;
      return {
        minX: x,
        minY: y,
        maxX: x + w,
        maxY: y + h,
        width: w,
        height: h,
        source: "element_mm",
      };
    }

    function sceneBounds() {
      var b = model.bounds || C.sceneRenderer.boundsFor(model.elements || []);
      // Guard invalid / empty
      if (!b || !(b.width > 0) || !(b.height > 0)) {
        var els = model.elements || [];
        if (els.length === 1) {
          var eb = elementBounds(els[0]);
          if (eb) return eb;
        }
        return { minX: 0, minY: 0, maxX: 1000, maxY: 1000, width: 1000, height: 1000, source: "fallback" };
      }
      return Object.assign({}, b, { source: "scene_mm" });
    }

    function readViewportSize() {
      var rect = vpEl.getBoundingClientRect();
      var vw = rect.width || lastVpSize.w || 800;
      var vh = rect.height || lastVpSize.h || 600;
      if (!(vw > 0) || !isFinite(vw)) vw = 800;
      if (!(vh > 0) || !isFinite(vh)) vh = 600;
      return { w: vw, h: vh };
    }

    function applyFitBounds(bounds) {
      var size = readViewportSize();
      viewport.fit(bounds, size.w, size.h, 56);
      lastVpSize = { w: size.w, h: size.h };
      paint();
    }

    /** Fit Priority 2 — entire filtered scene in engineering mm. */
    function fitScene() {
      applyFitBounds(sceneBounds());
    }

    /** Fit Priority 1 — selected element mm; falls back to scene. */
    function fitSelected() {
      var sel = selection.snapshot();
      var primary = sel.primaryId || sel.primaryElementId;
      if (primary) {
        var el = model.elements.filter(function (e) {
          return e.elementId === primary;
        })[0];
        var eb = elementBounds(el);
        if (eb) {
          applyFitBounds(eb);
          return;
        }
      }
      fitScene();
    }

    /**
     * Fit button / F — selected if present else scene.
     * Never uses SVG viewBox for bounds (artwork ≠ world mm).
     */
    function fitToSelectionOrScene() {
      var sel = selection.snapshot();
      var primary = sel.primaryId || sel.primaryElementId;
      if (primary) fitSelected();
      else fitScene();
    }

    function fit() {
      fitToSelectionOrScene();
    }

    /** Always recovers a visible centered design (Fit Priority 2). */
    function resetView() {
      viewport.reset();
      fitScene();
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

    function setActiveTool(tool) {
      C.commands.setActiveTool(cmdState, tool);
      syncChrome();
      paint();
    }

    /**
     * Paint adapter SVG. Fit ONCE when pendingPreviewFit is set (first resolve),
     * never on every property-driven preview refresh.
     * Stale D0 revision callers pass opts.renderRevision to skip viewport changes.
     */
    function setElementPreviewSvg(elementId, svg, opts) {
      opts = opts || {};
      if (!elementId) return;
      if (opts.renderRevision != null && opts.expectedRevision != null) {
        if (Number(opts.renderRevision) !== Number(opts.expectedRevision)) return;
      }
      model.previewContext.previewByElementId[elementId] = svg;
      paint();
      var shouldFit = !!pendingPreviewFit[elementId];
      if (shouldFit) {
        delete pendingPreviewFit[elementId];
        var sel = selection.snapshot();
        if (sel.primaryId === elementId || model.elements.length <= 1) {
          fitSelected();
        } else {
          fitScene();
        }
      }
    }

    function setSaveStatus(status, detail) {
      cmdState.saveStatus = status || "unsaved";
      if (savePill && detail) savePill.title = detail;
      C.workspace.syncSavePill(savePill, cmdState.saveStatus);
      emitCommand();
    }

    function syncSaveFromApp() {
      try {
        var pill = global.document && global.document.getElementById("savePill");
        if (pill && pill.dataset && pill.dataset.kind) {
          var k = pill.dataset.kind;
          if (k === "server_draft" || k === "revision") setSaveStatus("saved", pill.title || "");
          else if (k === "error") setSaveStatus("error", pill.title || "");
          else if (k === "unsaved") setSaveStatus("unsaved", pill.title || "");
          else setSaveStatus("local", pill.title || "");
        }
      } catch (e) {}
    }

    function getViewModel() {
      return {
        host: "UniversalCanvas",
        batch: "CANVAS-D",
        elements: model.elements,
        connections: model.connections,
        bounds: model.bounds,
        selection: selection.snapshot(),
        selected: model.selectedSync,
        viewport: viewport.snapshot(),
        commandState: getCommandState(),
        filterFloorId: model.filterFloorId,
        filterLocationId: model.filterLocationId,
        elementDragEnabled: false,
        grid: grid.snapshot(),
        snap: snap.snapshot(),
      };
    }

    function getSelectedDims() {
      var s = model.selectedSync;
      if (!s) return null;
      return { widthMm: s.widthMm, heightMm: s.heightMm, elementId: s.elementId };
    }

    function pushHistory(type, before, after, payload) {
      return history.push({ type: type, before: before, after: after, payload: payload || {} });
    }

    function undo() {
      var cmd = history.undo();
      // Infrastructure-only in Batch D unless a safe domain apply exists.
      paint();
      return cmd;
    }

    function redo() {
      var cmd = history.redo();
      paint();
      return cmd;
    }

    // Wire toolbar
    rootEl.querySelector('[data-uc="fit"]').onclick = fit;
    rootEl.querySelector('[data-uc="zoomIn"]').onclick = zoomIn;
    rootEl.querySelector('[data-uc="zoomOut"]').onclick = zoomOut;
    rootEl.querySelector('[data-uc="reset"]').onclick = resetView;
    if (undoBtn)
      undoBtn.onclick = function () {
        undo();
      };
    if (redoBtn)
      redoBtn.onclick = function () {
        redo();
      };
    if (gridBtn)
      gridBtn.onclick = function () {
        grid.toggle();
        cmdState.gridVisible = grid.visible;
        paint();
      };
    if (snapBtn)
      snapBtn.onclick = function () {
        snap.toggle();
        cmdState.snapEnabled = snap.enabled;
        syncChrome();
      };
    var propsToggle = rootEl.querySelector('[data-uc="toggleProps"]');
    if (propsToggle) {
      propsToggle.onclick = function () {
        shell.workspace.classList.toggle("is-props-collapsed");
        // ResizeObserver preserves zoom — do not call fit()
      };
    }

    shell.toolRail.querySelectorAll("[data-uc-tool]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (btn.disabled) return;
        setActiveTool(btn.getAttribute("data-uc-tool"));
      });
    });

    if (floorSel) {
      floorSel.onchange = function () {
        model.filterFloorId = floorSel.value || null;
        model.filterLocationId = null;
        refillLocations();
        applyFilters();
        fitScene();
      };
    }
    if (locSel) {
      locSel.onchange = function () {
        model.filterLocationId = locSel.value || null;
        applyFilters();
        fitScene();
      };
    }

    selection.onChange(function (snapSel) {
      paint();
      onSelectCbs.forEach(function (fn) {
        try {
          fn(model.selectedSync, snapSel);
        } catch (e) {}
      });
    });
    history.onChange(function () {
      syncChrome();
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
      var tool = cmdState.activeTool;
      var t = ev.target;
      var elNode = t && t.closest ? t.closest("[data-element-id]") : null;

      if (tool === C.commands.TOOLS.PAN || ev.button === 1) {
        panning = { x: ev.clientX, y: ev.clientY, pointerId: ev.pointerId };
        try {
          vpEl.setPointerCapture(ev.pointerId);
        } catch (e) {}
        vpEl.classList.add("is-panning");
        return;
      }

      if (elNode && (tool === C.commands.TOOLS.SELECT || tool === C.commands.TOOLS.MEASURE)) {
        var additive = !!(ev.ctrlKey || ev.metaKey || ev.shiftKey);
        selection.select(elNode.getAttribute("data-element-id"), additive, "element");
        return;
      }

      if (tool === C.commands.TOOLS.SELECT && (ev.button === 0 || ev.button === 1)) {
        // Background pan with select tool (legacy-friendly) OR clear selection
        if (ev.button === 1) {
          panning = { x: ev.clientX, y: ev.clientY, pointerId: ev.pointerId };
          try {
            vpEl.setPointerCapture(ev.pointerId);
          } catch (e) {}
          vpEl.classList.add("is-panning");
        } else {
          selection.clear();
        }
      }
    });

    vpEl.addEventListener("pointermove", function (ev) {
      var rect = vpEl.getBoundingClientRect();
      var world = viewport.viewportToWorld(ev.clientX - rect.left, ev.clientY - rect.top);
      if (snap.enabled) {
        var sp = snap.snapPoint(world.xMm, world.yMm, {
          zoom: viewport.zoom,
          elements: model.elements,
          gridMm: grid.spacingForZoom(viewport.zoom).minorMm,
        });
        updateCursorStatus({ xMm: sp.xMm, yMm: sp.yMm });
      } else {
        updateCursorStatus(world);
      }

      var hoverNode = ev.target && ev.target.closest ? ev.target.closest("[data-element-id]") : null;
      selection.setHover(hoverNode ? hoverNode.getAttribute("data-element-id") : null);

      if (!panning) return;
      viewport.panBy(ev.clientX - panning.x, ev.clientY - panning.y);
      panning.x = ev.clientX;
      panning.y = ev.clientY;
      paint();
    });

    function endPan(ev) {
      if (!panning) return;
      panning = null;
      vpEl.classList.remove("is-panning");
      try {
        if (ev && ev.pointerId != null) vpEl.releasePointerCapture(ev.pointerId);
      } catch (e) {}
    }
    vpEl.addEventListener("pointerup", endPan);
    vpEl.addEventListener("pointercancel", endPan);

    // ResizeObserver — preserve zoom/center when props panel toggles
    if (typeof ResizeObserver !== "undefined") {
      var ro = new ResizeObserver(function (entries) {
        var entry = entries && entries[0];
        if (!entry) return;
        var cr = entry.contentRect;
        var nw = cr.width;
        var nh = cr.height;
        if (lastVpSize.w > 0 && lastVpSize.h > 0 && nw > 0 && nh > 0) {
          if (Math.abs(nw - lastVpSize.w) > 1 || Math.abs(nh - lastVpSize.h) > 1) {
            viewport.preserveCenterOnResize(lastVpSize.w, lastVpSize.h, nw, nh);
            paint();
          }
        }
        lastVpSize = { w: nw, h: nh };
      });
      ro.observe(vpEl);
    }

    // Keyboard shortcuts with input-focus guard
    function onKey(ev) {
      if (!C.commands.keyboardShortcutAllowed(ev.target)) return;
      var key = ev.key;
      var mod = ev.ctrlKey || ev.metaKey;
      if (key === "Escape") {
        setActiveTool(C.commands.TOOLS.SELECT);
        return;
      }
      if (key === "f" || key === "F") {
        if (!mod) {
          ev.preventDefault();
          fit();
        }
        return;
      }
      if (mod && key.toLowerCase() === "z" && !ev.shiftKey) {
        ev.preventDefault();
        undo();
        return;
      }
      if ((mod && key.toLowerCase() === "y") || (mod && ev.shiftKey && key.toLowerCase() === "z")) {
        ev.preventDefault();
        redo();
        return;
      }
      // Delete intentionally no-op (disabled) — avoid browser-only deletion
    }
    vpEl.addEventListener("keydown", onKey);
    rootEl.addEventListener("keydown", onKey);

    // Observe app save pill for B2 durability honesty
    try {
      var appPill = global.document && global.document.getElementById("savePill");
      if (appPill && global.MutationObserver) {
        new MutationObserver(function () {
          syncSaveFromApp();
        }).observe(appPill, { attributes: true, childList: true, characterData: true, subtree: true });
      }
      syncSaveFromApp();
    } catch (e) {}

    syncChrome();
    paint();

    return {
      loadScene: loadScene,
      fit: fit,
      fitScene: fitScene,
      fitSelected: fitSelected,
      fitToSelectionOrScene: fitToSelectionOrScene,
      resetView: resetView,
      zoomIn: zoomIn,
      zoomOut: zoomOut,
      setActiveTool: setActiveTool,
      setElementPreviewSvg: setElementPreviewSvg,
      markPendingPreviewFit: markPendingPreviewFit,
      upsertLocalElement: upsertLocalElement,
      selectElementById: selectElementById,
      setSaveStatus: setSaveStatus,
      getViewModel: getViewModel,
      getCommandState: getCommandState,
      getSelectedDims: getSelectedDims,
      pushHistory: pushHistory,
      undo: undo,
      redo: redo,
      snap: snap,
      grid: grid,
      history: history,
      selection: selection,
      viewport: viewport,
      registry: registry,
      propertyPanelEl: shell.propertyPanel,
      shell: shell,
      onSelect: function (fn) {
        if (typeof fn === "function") onSelectCbs.push(fn);
      },
      onCommandState: function (fn) {
        if (typeof fn === "function") onCommandCbs.push(fn);
      },
      paint: paint,
      isUniversalCanvas: true,
      batch: "CANVAS-D3",
    };
  }

  /**
   * Progressive SPA mount: wrap #livePreview when flag on; leave forms in DOM (hidden in UC mode).
   */
  function tryMount(options) {
    options = options || {};
    if (!isEnabled(options.serverEnabled)) return null;
    var live = global.document && global.document.getElementById("livePreview");
    if (!live) return null;
    var panel = live.closest(".cart-preview") || live.parentElement;
    if (!panel) return null;

    // D0/D1: ONE Universal Canvas only — never mount a second host.
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
        "display:flex;flex-direction:column;flex:1 1 auto;min-height:0;height:100%";
      live.style.display = "none";
      live.setAttribute("data-uc-compat", "1");
      live.setAttribute("aria-hidden", "true");
      panel.insertBefore(mount, live);
    }
    panel.classList.add("uc-active");
    var host;
    try {
      host = createHost(mount, options);
    } catch (eCreate) {
      console.warn("UniversalCanvas createHost failed", eCreate);
      try {
        if (C.workspace && C.workspace.applyPrimaryCutover) C.workspace.applyPrimaryCutover(false);
      } catch (e0) {}
      return null;
    }
    global.WEOS_UNIVERSAL_CANVAS_HOST = host;

    // Compatibility: keep zoom buttons wired.
    var fitBtn = global.document.getElementById("btnPrevFit");
    var zin = global.document.getElementById("btnPrevZoomIn");
    var zout = global.document.getElementById("btnPrevZoomOut");
    if (fitBtn)
      fitBtn.onclick = function () {
        host.fit();
      };
    if (zin)
      zin.onclick = function () {
        host.zoomIn();
      };
    if (zout)
      zout.onclick = function () {
        host.zoomOut();
      };

    try {
      if (C.workspace && C.workspace.applyPrimaryCutover) {
        C.workspace.applyPrimaryCutover(true);
      }
    } catch (eCut) {}

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
    qsFlag: qsFlag,
  };
  C.create = createHost;
})(typeof window !== "undefined" ? window : globalThis);
