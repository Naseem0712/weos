/**
 * WEOS Canvas Batch E — Member / Grid / Cell drawing (real engineering tools).
 * World mm only. Confirm → POST → reload topology. Esc cancels ghost.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  function sessionHeaders() {
    var h = { "Content-Type": "application/json" };
    try {
      var s =
        (global.WEOS_SESSION && global.WEOS_SESSION.id) ||
        (global.localStorage && global.localStorage.getItem("weosSession")) ||
        "";
      if (s) h["X-WEOS-Session"] = s;
    } catch (e) {}
    return h;
  }

  function api(path, opts) {
    opts = opts || {};
    return fetch(path, {
      method: opts.method || "GET",
      headers: sessionHeaders(),
      body: opts.body != null ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) {
          var err = new Error((j && (j.detail || j.error)) || r.statusText || "request failed");
          err.status = r.status;
          err.payload = j;
          throw err;
        }
        return j;
      });
    });
  }

  function createMemberTools(host) {
    var state = {
      ghost: null, // { orientation, positionMm, elementId, cellId, x1,y1,x2,y2, label }
      hoverCellId: null,
      topologyByElement: Object.create(null),
      structureEnabled: false,
      lastRevisionId: null,
    };
    var overlayEl = null;

    function ensureOverlay(vpEl) {
      if (overlayEl && overlayEl.parentNode) return overlayEl;
      overlayEl = document.createElement("div");
      overlayEl.className = "uc-layer uc-layer--structure";
      overlayEl.setAttribute("data-layer", "structure");
      overlayEl.style.position = "absolute";
      overlayEl.style.left = "0";
      overlayEl.style.top = "0";
      overlayEl.style.width = "100%";
      overlayEl.style.height = "100%";
      overlayEl.style.pointerEvents = "none";
      overlayEl.style.zIndex = "4";
      if (vpEl) vpEl.appendChild(overlayEl);
      return overlayEl;
    }

    function setStructureEnabled(on) {
      state.structureEnabled = !!on;
    }

    function cacheTopology(elementId, topo) {
      if (!elementId) return;
      state.topologyByElement[String(elementId)] = topo || null;
      if (topo && topo.revision && topo.revision.revisionId) {
        state.lastRevisionId = topo.revision.revisionId;
      }
    }

    function loadTopology(elementId) {
      if (!elementId) return Promise.resolve(null);
      return api("/api/elements/" + encodeURIComponent(elementId) + "/structure").then(function (topo) {
        cacheTopology(elementId, topo);
        return topo;
      });
    }

    function cancelGhost() {
      state.ghost = null;
      state.hoverCellId = null;
      paintGhost();
    }

    function paintGhost() {
      if (!overlayEl) return;
      var g = state.ghost;
      var html = "";
      if (g) {
        html +=
          '<svg class="uc-structure-ghost" style="position:absolute;left:0;top:0;overflow:visible;pointer-events:none">' +
          '<line x1="' +
          g.x1 +
          '" y1="' +
          g.y1 +
          '" x2="' +
          g.x2 +
          '" y2="' +
          g.y2 +
          '" stroke="#2563eb" stroke-width="2" stroke-dasharray="6 4"/>' +
          '<text x="' +
          (g.x1 + g.x2) / 2 +
          '" y="' +
          ((g.y1 + g.y2) / 2 - 8) +
          '" fill="#2563eb" font-size="12" text-anchor="middle">' +
          String(Math.round(g.positionMm)) +
          " mm</text></svg>";
      }
      var ghostHost = overlayEl.querySelector(".uc-structure-ghost-host");
      if (!ghostHost) {
        ghostHost = document.createElement("div");
        ghostHost.className = "uc-structure-ghost-host";
        ghostHost.style.position = "absolute";
        ghostHost.style.left = "0";
        ghostHost.style.top = "0";
        ghostHost.style.width = "100%";
        ghostHost.style.height = "100%";
        ghostHost.style.pointerEvents = "none";
        overlayEl.appendChild(ghostHost);
      }
      ghostHost.innerHTML = html;
    }

    function paintTopology(viewport, elements) {
      ensureOverlay(host && host.viewport);
      if (!overlayEl) return;
      var xform =
        viewport && typeof viewport.cssTransform === "function"
          ? viewport.cssTransform()
          : "";
      overlayEl.style.transform = xform;
      overlayEl.style.transformOrigin = "0 0";

      var parts = [];
      (elements || []).forEach(function (el) {
        var topo = state.topologyByElement[el.elementId];
        if (!topo || !topo.gridActivated) return;
        var ox = Number(el.xMm) || 0;
        var oy = Number(el.yMm) || 0;
        (topo.cells || []).forEach(function (cell) {
          if (!cell.isLeaf) return;
          var sel = state.hoverCellId === cell.cellId ? " is-hover" : "";
          parts.push(
            '<div class="uc-cell' +
              sel +
              '" data-cell-id="' +
              String(cell.cellId).replace(/"/g, "") +
              '" data-element-id="' +
              String(el.elementId).replace(/"/g, "") +
              '" style="position:absolute;left:' +
              (ox + Number(cell.xMm || 0)) +
              "px;top:" +
              (oy + Number(cell.yMm || 0)) +
              "px;width:" +
              Number(cell.widthMm || 0) +
              "px;height:" +
              Number(cell.heightMm || 0) +
              'px;pointer-events:auto;box-sizing:border-box"></div>'
          );
        });
        (topo.members || []).forEach(function (m) {
          var x1 = ox + Number(m.x1Mm || 0);
          var y1 = oy + Number(m.y1Mm || 0);
          var x2 = ox + Number(m.x2Mm || 0);
          var y2 = oy + Number(m.y2Mm || 0);
          parts.push(
            '<div class="uc-member" data-member-id="' +
              String(m.memberId).replace(/"/g, "") +
              '" data-element-id="' +
              String(el.elementId).replace(/"/g, "") +
              '" data-orientation="' +
              String(m.orientation || "") +
              '" style="position:absolute;left:' +
              Math.min(x1, x2) +
              "px;top:" +
              Math.min(y1, y2) +
              "px;width:" +
              Math.max(4, Math.abs(x2 - x1) || 4) +
              "px;height:" +
              Math.max(4, Math.abs(y2 - y1) || 4) +
              'px;pointer-events:auto"></div>'
          );
        });
      });
      var solid = overlayEl.querySelector(".uc-structure-solid");
      if (!solid) {
        solid = document.createElement("div");
        solid.className = "uc-structure-solid";
        solid.style.position = "absolute";
        solid.style.left = "0";
        solid.style.top = "0";
        solid.style.width = "100%";
        solid.style.height = "100%";
        overlayEl.insertBefore(solid, overlayEl.firstChild);
      }
      solid.innerHTML = parts.join("");
      paintGhost();
    }

    function findElementAt(elements, worldX, worldY) {
      for (var i = (elements || []).length - 1; i >= 0; i--) {
        var el = elements[i];
        var x = Number(el.xMm) || 0;
        var y = Number(el.yMm) || 0;
        var w = Number(el.widthMm) || 0;
        var h = Number(el.heightMm) || 0;
        if (worldX >= x && worldX <= x + w && worldY >= y && worldY <= y + h) return el;
      }
      return null;
    }

    function findLeafCell(topo, localX, localY) {
      if (!topo) return null;
      var cells = topo.cells || [];
      for (var i = 0; i < cells.length; i++) {
        var c = cells[i];
        if (!c.isLeaf) continue;
        if (
          localX >= c.xMm &&
          localX <= c.xMm + c.widthMm &&
          localY >= c.yMm &&
          localY <= c.yMm + c.heightMm
        ) {
          return c;
        }
      }
      return null;
    }

    function updateGhost(tool, world, elements, snapFn) {
      var ori = tool === "member_h" ? "H" : "V";
      if (tool === "member") ori = "V";
      var pt = world;
      if (typeof snapFn === "function") {
        pt = snapFn(world.xMm, world.yMm) || world;
      }
      var el = findElementAt(elements, pt.xMm, pt.yMm);
      if (!el) {
        state.ghost = null;
        state.hoverCellId = null;
        paintGhost();
        return null;
      }
      var localX = pt.xMm - (Number(el.xMm) || 0);
      var localY = pt.yMm - (Number(el.yMm) || 0);
      var topo = state.topologyByElement[el.elementId];
      var cell = findLeafCell(topo, localX, localY);
      state.hoverCellId = cell ? cell.cellId : null;
      var x1, y1, x2, y2, pos;
      if (ori === "V") {
        pos = localX;
        if (cell) {
          y1 = (Number(el.yMm) || 0) + cell.yMm;
          y2 = y1 + cell.heightMm;
        } else {
          y1 = Number(el.yMm) || 0;
          y2 = y1 + (Number(el.heightMm) || 0);
        }
        x1 = x2 = (Number(el.xMm) || 0) + pos;
      } else {
        pos = localY;
        if (cell) {
          x1 = (Number(el.xMm) || 0) + cell.xMm;
          x2 = x1 + cell.widthMm;
        } else {
          x1 = Number(el.xMm) || 0;
          x2 = x1 + (Number(el.widthMm) || 0);
        }
        y1 = y2 = (Number(el.yMm) || 0) + pos;
      }
      state.ghost = {
        orientation: ori,
        positionMm: pos,
        elementId: el.elementId,
        cellId: cell ? cell.cellId : null,
        x1: x1,
        y1: y1,
        x2: x2,
        y2: y2,
      };
      paintGhost();
      return state.ghost;
    }

    function confirmGhost() {
      var g = state.ghost;
      if (!g || !g.elementId) return Promise.reject(new Error("no ghost"));
      return api("/api/elements/" + encodeURIComponent(g.elementId) + "/members", {
        method: "POST",
        body: {
          orientation: g.orientation,
          positionMm: g.positionMm,
          cellId: g.cellId || undefined,
          expectedRevisionId: state.lastRevisionId || undefined,
        },
      }).then(function (res) {
        cancelGhost();
        if (res.topology) cacheTopology(g.elementId, res.topology);
        if (res.revision && res.revision.revisionId) state.lastRevisionId = res.revision.revisionId;
        return res;
      });
    }

    function applyGrid(elementId, rows, columns) {
      return api("/api/elements/" + encodeURIComponent(elementId) + "/grid", {
        method: "POST",
        body: {
          rows: rows,
          columns: columns,
          expectedRevisionId: state.lastRevisionId || undefined,
        },
      }).then(function (res) {
        if (res.topology) cacheTopology(elementId, res.topology);
        if (res.revision && res.revision.revisionId) state.lastRevisionId = res.revision.revisionId;
        return res;
      });
    }

    function promptGrid(elementId) {
      var raw = global.prompt("Equal grid Rows×Columns (e.g. 2x3)", "2x2");
      if (!raw) return Promise.resolve(null);
      var m = String(raw).trim().match(/^(\d+)\s*[x×]\s*(\d+)$/i);
      if (!m) return Promise.reject(new Error("Enter Rows×Columns like 2x3"));
      return applyGrid(elementId, parseInt(m[1], 10), parseInt(m[2], 10));
    }

    function deleteMember(memberId) {
      var q = state.lastRevisionId
        ? "?expectedRevisionId=" + encodeURIComponent(state.lastRevisionId)
        : "";
      return api("/api/members/" + encodeURIComponent(memberId) + q, { method: "DELETE" });
    }

    function undo(elementId) {
      return api("/api/elements/" + encodeURIComponent(elementId) + "/structure/undo", {
        method: "POST",
        body: {},
      }).then(function (res) {
        if (res.topology) cacheTopology(elementId, res.topology);
        return res;
      });
    }

    function redo(elementId) {
      return api("/api/elements/" + encodeURIComponent(elementId) + "/structure/redo", {
        method: "POST",
        body: {},
      }).then(function (res) {
        if (res.topology) cacheTopology(elementId, res.topology);
        return res;
      });
    }

    function updateMemberPosition(memberId, positionMm) {
      return api("/api/members/" + encodeURIComponent(memberId), {
        method: "PATCH",
        body: {
          positionMm: positionMm,
          expectedRevisionId: state.lastRevisionId || undefined,
        },
      });
    }

    return {
      state: state,
      ensureOverlay: ensureOverlay,
      setStructureEnabled: setStructureEnabled,
      loadTopology: loadTopology,
      cacheTopology: cacheTopology,
      cancelGhost: cancelGhost,
      updateGhost: updateGhost,
      confirmGhost: confirmGhost,
      paintTopology: paintTopology,
      promptGrid: promptGrid,
      applyGrid: applyGrid,
      deleteMember: deleteMember,
      undo: undo,
      redo: redo,
      updateMemberPosition: updateMemberPosition,
      findElementAt: findElementAt,
    };
  }

  C.memberTools = { create: createMemberTools, BATCH: "CANVAS-E" };
})(typeof window !== "undefined" ? window : globalThis);
