/**
 * WEOS Universal Canvas — Scene renderer (layered: grid / world / conn / dims / UI).
 */
(function (global) {
  "use strict";

  function flattenElements(scene) {
    var out = [];
    function pack(el, floor, location, assembly) {
      out.push({
        elementId: el.elementId,
        displayCode: el.displayCode,
        productType: el.productType,
        productId: el.productId,
        widthMm: Number(el.widthMm) || 0,
        heightMm: Number(el.heightMm) || 0,
        xMm: Number(el.xMm) || 0,
        yMm: Number(el.yMm) || 0,
        orientation: el.orientation,
        assemblyId: assembly && assembly.assemblyId,
        assemblyDisplayCode: assembly && assembly.displayCode,
        floorId: floor && floor.floorId,
        floorCode: floor && floor.code,
        floorName: floor && floor.name,
        locationId: (location && location.locationId) || (assembly && assembly.locationId),
        locationCode: location && location.code,
        locationName: location && location.name,
        designDocumentId: el.designDocumentId || (scene && scene.designDocumentId),
        projectId: el.projectId || (scene && scene.projectId),
        geometryPayload: el.geometryPayload,
        configPayload: el.configPayload,
        status: el.status,
      });
    }
    (scene.floors || []).forEach(function (fl) {
      (fl.locations || []).forEach(function (loc) {
        (loc.assemblies || []).forEach(function (asm) {
          (asm.elements || []).forEach(function (el) {
            pack(el, fl, loc, asm);
          });
        });
      });
    });
    (scene.unlocatedAssemblies || []).forEach(function (asm) {
      (asm.elements || []).forEach(function (el) {
        pack(el, null, null, asm);
      });
    });
    return out;
  }

  function flattenConnections(scene) {
    var out = [];
    var seen = Object.create(null);
    function take(asm) {
      (asm.connections || []).forEach(function (c) {
        if (!c || !c.connectionId || seen[c.connectionId]) return;
        seen[c.connectionId] = true;
        out.push({
          connectionId: c.connectionId,
          assemblyId: c.assemblyId || asm.assemblyId,
          elementAId: c.elementAId,
          elementBId: c.elementBId,
          connectionType: c.connectionType,
          sideA: c.sideA,
          sideB: c.sideB,
          parameters: c.parameters,
        });
      });
    }
    (scene.floors || []).forEach(function (fl) {
      (fl.locations || []).forEach(function (loc) {
        (loc.assemblies || []).forEach(take);
      });
    });
    (scene.unlocatedAssemblies || []).forEach(take);
    return out;
  }

  function boundsFor(elements) {
    if (!elements.length) {
      return { minX: 0, minY: 0, maxX: 1000, maxY: 1000, width: 1000, height: 1000 };
    }
    var minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    elements.forEach(function (e) {
      minX = Math.min(minX, e.xMm);
      minY = Math.min(minY, e.yMm);
      maxX = Math.max(maxX, e.xMm + e.widthMm);
      maxY = Math.max(maxY, e.yMm + e.heightMm);
    });
    return {
      minX: minX,
      minY: minY,
      maxX: maxX,
      maxY: maxY,
      width: Math.max(1, maxX - minX),
      height: Math.max(1, maxY - minY),
    };
  }

  function ensureLayers(hostEl) {
    if (!hostEl.querySelector(".uc-layer--grid")) {
      hostEl.innerHTML =
        '<div class="uc-layer uc-layer--grid" data-layer="grid"></div>' +
        '<div class="uc-layer uc-layer--world uc-world" data-layer="world"></div>' +
        '<div class="uc-layer uc-layer--conn uc-conn" data-layer="conn"></div>' +
        '<div class="uc-layer uc-layer--dims" data-layer="dims"></div>' +
        '<div class="uc-layer uc-layer--ui" data-layer="ui"></div>';
    }
    return {
      grid: hostEl.querySelector(".uc-layer--grid"),
      world: hostEl.querySelector(".uc-layer--world"),
      conn: hostEl.querySelector(".uc-layer--conn"),
      dims: hostEl.querySelector(".uc-layer--dims"),
      ui: hostEl.querySelector(".uc-layer--ui"),
    };
  }

  function renderInto(hostEl, model, viewport, selection, registry, extras) {
    if (!hostEl) return;
    extras = extras || {};
    var elements = model.elements || [];
    var connections = model.connections || [];
    var byId = Object.create(null);
    elements.forEach(function (e) {
      byId[e.elementId] = e;
    });

    var layers = ensureLayers(hostEl);
    var snap = viewport.snapshot();
    var xform =
      typeof viewport.cssTransform === "function"
        ? viewport.cssTransform()
        : "translate(" + snap.panX + "px," + snap.panY + "px) scale(" + snap.zoom + ")";
    layers.world.style.transform = xform;
    layers.world.style.transformOrigin = "0 0";
    layers.conn.style.transform = xform;
    layers.conn.style.transformOrigin = "0 0";

    // Empty state (UI layer — not product SVG)
    if (!elements.length) {
      layers.world.innerHTML = "";
      layers.conn.innerHTML = "";
      layers.ui.innerHTML =
        '<div class="uc-empty-state weos-ds-state">' +
        '<p class="uc-empty-state__title">No design yet</p>' +
        '<p class="uc-empty-state__text">Add a design from the project workflow, or select a product to begin. The canvas stays empty until you confirm an action.</p>' +
        "</div>";
    } else {
      layers.ui.innerHTML = "";
    }

    // Grid layer (viewport-only)
    if (extras.grid && typeof extras.grid.paintInto === "function") {
      extras.grid.paintInto(layers.grid, viewport, boundsFor(elements));
    } else {
      layers.grid.innerHTML = "";
    }

    var html = "";
    var selSnap = selection.snapshot ? selection.snapshot() : {};
    var hoverId = selSnap.hoverId || null;
    elements.forEach(function (el) {
      var rendered = registry.render(el, model.previewContext || {});
      var sel = selection.isSelected(el.elementId);
      var hover = hoverId && hoverId === el.elementId && !sel;
      var unsupported = rendered && rendered.usedFallback;
      var label = el.displayCode || el.elementId;
      var cls = "uc-el";
      if (sel) cls += " uc-el-selected";
      if (hover) cls += " uc-el-hover";
      if (unsupported) cls += " uc-el-unsupported";
      html +=
        '<div class="' +
        cls +
        '" data-element-id="' +
        String(el.elementId).replace(/"/g, "") +
        '" data-assembly-id="' +
        String(el.assemblyId || "").replace(/"/g, "") +
        '" style="position:absolute;left:' +
        el.xMm +
        "px;top:" +
        el.yMm +
        "px;width:" +
        el.widthMm +
        "px;height:" +
        el.heightMm +
        'px;box-sizing:border-box;cursor:pointer">' +
        '<div class="uc-el-svg" style="width:100%;height:100%;overflow:hidden">' +
        (rendered.svg || "") +
        "</div>" +
        '<div class="uc-el-label" style="position:absolute;left:4px;top:4px;background:rgba(255,255,255,.85);' +
        "padding:2px 6px;font:12px/1.2 Segoe UI,sans-serif;pointer-events:none\">" +
        String(label).replace(/</g, "") +
        "</div>" +
        "</div>";
    });
    layers.world.innerHTML = html;

    // Connections — separate overlay layer
    var svgParts = [];
    var bb = boundsFor(elements);
    var vbW = bb.width + 200;
    var vbH = bb.height + 200;
    svgParts.push(
      '<svg xmlns="http://www.w3.org/2000/svg" width="' +
        vbW +
        '" height="' +
        vbH +
        '" style="overflow:visible;position:absolute;left:' +
        (bb.minX - 100) +
        "px;top:" +
        (bb.minY - 100) +
        'px">'
    );
    connections.forEach(function (c) {
      var a = byId[c.elementAId];
      var b = byId[c.elementBId];
      if (!a || !b) return;
      var ax = a.xMm + a.widthMm / 2 - (bb.minX - 100);
      var ay = a.yMm + a.heightMm / 2 - (bb.minY - 100);
      var bx = b.xMm + b.widthMm / 2 - (bb.minX - 100);
      var by = b.yMm + b.heightMm / 2 - (bb.minY - 100);
      svgParts.push(
        '<line x1="' +
          ax +
          '" y1="' +
          ay +
          '" x2="' +
          bx +
          '" y2="' +
          by +
          '" stroke="#6a7a8a" stroke-width="4" stroke-dasharray="12 8" data-connection-id="' +
          String(c.connectionId || "").replace(/"/g, "") +
          '"/>'
      );
    });
    svgParts.push("</svg>");
    layers.conn.innerHTML = svgParts.join("");

    // Dimensions — separate overlay (engineering mm)
    if (extras.dimensions && typeof extras.dimensions.paintInto === "function") {
      var ids = selSnap.selectedIds || selSnap.selectedElementIds || [];
      var overlays =
        typeof extras.dimensions.buildForSelection === "function"
          ? extras.dimensions.buildForSelection(elements, ids)
          : [];
      if (extras.showDimensions === false) overlays = [];
      extras.dimensions.paintInto(layers.dims, overlays, viewport);
    } else {
      layers.dims.innerHTML = "";
    }

    Array.prototype.forEach.call(layers.world.querySelectorAll(".uc-el-svg svg"), function (svg) {
      // Display-only normalization: artwork fills element box (widthMm×heightMm).
      // Element engineering bounds drive Fit — never SVG viewBox units.
      try {
        if (!svg.getAttribute("viewBox")) {
          var vbW = Number(elWidthFromParent(svg)) || 0;
          var vbH = Number(elHeightFromParent(svg)) || 0;
          if (vbW > 0 && vbH > 0) svg.setAttribute("viewBox", "0 0 " + vbW + " " + vbH);
        }
      } catch (eVb) {}
      svg.style.width = "100%";
      svg.style.height = "100%";
      svg.style.display = "block";
      svg.setAttribute("preserveAspectRatio", "none");
      svg.setAttribute("data-weos-artwork", "1");
    });
  }

  function elWidthFromParent(svg) {
    var host = svg && svg.closest && svg.closest(".uc-el");
    if (!host) return 0;
    return parseFloat(host.style.width) || 0;
  }

  function elHeightFromParent(svg) {
    var host = svg && svg.closest && svg.closest(".uc-el");
    if (!host) return 0;
    return parseFloat(host.style.height) || 0;
  }

  global.WEOSCanvas = global.WEOSCanvas || {};
  global.WEOSCanvas.sceneRenderer = {
    flattenElements: flattenElements,
    flattenConnections: flattenConnections,
    boundsFor: boundsFor,
    renderInto: renderInto,
    ensureLayers: ensureLayers,
  };
})(typeof window !== "undefined" ? window : globalThis);
