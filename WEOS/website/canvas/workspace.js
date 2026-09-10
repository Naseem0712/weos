/**
 * WEOS Canvas Batch D — Professional workspace chrome (tool rail + command bar + stage).
 * Wraps the ONE Universal Canvas host — does not create a second canvas.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  function esc(s) {
    return String(s == null ? "" : s).replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  function toolBtn(id, label, reserved) {
    var title = reserved ? label + " (coming next)" : label;
    return (
      '<button type="button" class="uc-tool' +
      (reserved ? " is-reserved" : "") +
      '" data-uc-tool="' +
      id +
      '"' +
      (reserved ? " disabled aria-disabled=\"true\"" : "") +
      ' title="' +
      esc(title) +
      '"><span class="uc-tool__label">' +
      esc(label) +
      "</span>" +
      (reserved ? '<span class="uc-tool__soon">soon</span>' : "") +
      "</button>"
    );
  }

  function buildShellHtml() {
    return (
      '<div class="uc-workspace" data-batch="CANVAS-D">' +
      '<div class="uc-command-bar weos-ds-toolbar" role="toolbar" aria-label="Canvas commands">' +
      '<div class="weos-ds-toolbar__group uc-cmd-identity">' +
      '<strong class="uc-cmd-title">Engineering Canvas</strong>' +
      '<span class="uc-cmd-design muted" data-uc="designLabel">Design</span>' +
      "</div>" +
      '<span class="weos-ds-toolbar__sep"></span>' +
      '<div class="weos-ds-toolbar__group">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="undo" disabled title="Undo">Undo</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="redo" disabled title="Redo">Redo</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="delete" disabled title="Delete unavailable">Delete</button>' +
      "</div>" +
      '<span class="weos-ds-toolbar__sep"></span>' +
      '<div class="weos-ds-toolbar__group">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="zoomOut" title="Zoom out">−</button>' +
      '<span class="uc-zoom-label muted" data-uc="zoomLabel">100%</span>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="zoomIn" title="Zoom in">+</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="fit" title="Fit">Fit</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="reset" title="Reset view">Reset</button>' +
      "</div>" +
      '<span class="weos-ds-toolbar__sep"></span>' +
      '<div class="weos-ds-toolbar__group">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="gridToggle" title="Toggle grid">Grid</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="snapToggle" title="Toggle snap">Snap</button>' +
      '<label class="muted uc-floor-label" style="font-size:.72rem">Floor <select id="ucFloorSel" class="weos-ds-select"></select></label>' +
      '<label class="muted uc-floor-label" style="font-size:.72rem">Loc <select id="ucLocSel" class="weos-ds-select"></select></label>' +
      "</div>" +
      '<span class="weos-ds-toolbar__spacer"></span>' +
      '<div class="weos-ds-toolbar__group">' +
      '<span class="weos-ds-pill uc-save-pill" data-uc="saveStatus" data-kind="local">Local recovery</span>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm uc-props-toggle" data-uc="toggleProps" title="Toggle properties">Props</button>' +
      "</div>" +
      "</div>" +
      '<div class="uc-workspace-body">' +
      '<aside class="uc-tool-rail" aria-label="Canvas tools">' +
      toolBtn("select", "Select", false) +
      toolBtn("pan", "Pan", false) +
      toolBtn("measure", "Dim", false) +
      '<div class="uc-tool-rail__sep"></div>' +
      toolBtn("member", "Member", true) +
      toolBtn("member_v", "V-Mem", true) +
      toolBtn("member_h", "H-Mem", true) +
      toolBtn("grid_split", "Grid", true) +
      "</aside>" +
      '<div class="uc-stage-wrap">' +
      '<div class="uc-viewport" tabindex="0" aria-label="Engineering viewport"></div>' +
      '<div class="uc-status-bar muted">' +
      '<span data-uc="cursorStatus">X — · Y — · Zoom 100%</span>' +
      '<span data-uc="selinfo">No selection</span>' +
      "</div>" +
      "</div>" +
      '<aside class="uc-props-rail" id="ucPropertyPanelHost" aria-label="Properties">' +
      '<div id="ucPropertyPanel" class="uc-property-panel"></div>' +
      "</aside>" +
      "</div>" +
      "</div>"
    );
  }

  function mountShell(rootEl) {
    if (!rootEl) throw new Error("workspace root required");
    rootEl.classList.add("uc-host", "uc-host--workspace");
    rootEl.innerHTML = buildShellHtml();
    return {
      workspace: rootEl.querySelector(".uc-workspace"),
      commandBar: rootEl.querySelector(".uc-command-bar"),
      toolRail: rootEl.querySelector(".uc-tool-rail"),
      viewport: rootEl.querySelector(".uc-viewport"),
      propsRail: rootEl.querySelector(".uc-props-rail"),
      propertyPanel: rootEl.querySelector("#ucPropertyPanel"),
      statusBar: rootEl.querySelector(".uc-status-bar"),
    };
  }

  function syncToolRail(toolRail, activeTool) {
    if (!toolRail) return;
    toolRail.querySelectorAll("[data-uc-tool]").forEach(function (btn) {
      var id = btn.getAttribute("data-uc-tool");
      var on = id === activeTool && !btn.disabled;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function syncSavePill(el, status) {
    if (!el) return;
    var labels = {
      local: "Local recovery",
      unsaved: "Unsaved",
      saving: "Saving…",
      saved: "Saved",
      error: "Save failed",
      server_draft: "Saved",
    };
    el.textContent = labels[status] || String(status || "Unsaved");
    el.dataset.kind = status || "unsaved";
  }

  C.workspace = {
    buildShellHtml: buildShellHtml,
    mountShell: mountShell,
    syncToolRail: syncToolRail,
    syncSavePill: syncSavePill,
  };
})(typeof window !== "undefined" ? window : globalThis);
