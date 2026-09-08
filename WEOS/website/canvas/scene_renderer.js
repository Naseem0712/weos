/**
 * WEOS Universal Canvas — Scene renderer (elements + explicit connections).
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

  function renderInto(hostEl, model, viewport, selection, registry) {
    if (!hostEl) return;
    var elements = model.elements || [];
    var connections = model.connections || [];
    var byId = Object.create(null);
    elements.forEach(function (e) {
      byId[e.elementId] = e;
    });

    var layer = hostEl.querySelector(".uc-world");
    if (!layer) {
      hostEl.innerHTML =
        '<div class="uc-world" style="position:absolute;left:0;top:0;transform-origin:0 0"></div>' +
        '<div class="uc-conn" style="position:absolute;left:0;top:0;pointer-events:none;overflow:visible"></div>';
      layer = hostEl.querySelector(".uc-world");
    }
    var connLayer = hostEl.querySelector(".uc-conn");
    var snap = viewport.snapshot();
    layer.style.transform =
      "translate(" + snap.panX + "px," + snap.panY + "px) scale(" + snap.zoom + ")";
    connLayer.style.transform = layer.style.transform;

    var html = "";
    elements.forEach(function (el) {
      var rendered = registry.render(el, model.previewContext || {});
      var sel = selection.isSelected(el.elementId);
      var label = el.displayCode || el.elementId;
      html +=
        '<div class="uc-el' +
        (sel ? " uc-el-selected" : "") +
        '" data-element-id="' +
        String(el.elementId).replace(/"/g, "") +
        '" style="position:absolute;left:' +
        el.xMm +
        "px;top:" +
        el.yMm +
        "px;width:" +
        el.widthMm +
        "px;height:" +
        el.heightMm +
        'px;box-sizing:border-box;cursor:pointer;' +
        (sel ? "outline:3px solid #c45c26;outline-offset:2px;" : "outline:1px solid rgba(0,0,0,.15);") +
        '">' +
        '<div class="uc-el-svg" style="width:100%;height:100%;overflow:hidden">' +
        (rendered.svg || "") +
        "</div>" +
        '<div class="uc-el-label" style="position:absolute;left:4px;top:4px;background:rgba(255,255,255,.85);' +
        "padding:2px 6px;font:12px/1.2 Segoe UI,sans-serif;pointer-events:none\">" +
        String(label).replace(/</g, "") +
        "</div>" +
        "</div>";
    });
    layer.innerHTML = html;

    // Explicit connections only — simple line viz between element centers.
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
    connLayer.innerHTML = svgParts.join("");

    // Normalize nested SVG to fill box without mutating engineering dims.
    Array.prototype.forEach.call(layer.querySelectorAll(".uc-el-svg svg"), function (svg) {
      svg.style.width = "100%";
      svg.style.height = "100%";
      svg.style.display = "block";
      svg.setAttribute("preserveAspectRatio", "none");
    });
  }

  global.WEOSCanvas = global.WEOSCanvas || {};
  global.WEOSCanvas.sceneRenderer = {
    flattenElements: flattenElements,
    flattenConnections: flattenConnections,
    boundsFor: boundsFor,
    renderInto: renderInto,
  };
})(typeof window !== "undefined" ? window : globalThis);
