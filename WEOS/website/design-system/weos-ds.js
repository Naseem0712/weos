/**
 * WEOS Application Design System — JS helpers (UX Batch C)
 * Progressive utilities for modal, side panel, tabs.
 * Does not replace legacy SPA dialogs; Canvas D+ and new screens may adopt.
 */
(function (global) {
  "use strict";

  var DS = global.WEOSDesignSystem || {};
  DS.version = "0.1.0";
  DS.batch = "UX-C";

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function lockScroll(lock) {
    try {
      document.documentElement.style.overflow = lock ? "hidden" : "";
    } catch (e) {}
  }

  /**
   * Open a modal root element (.weos-ds-modal-root).
   * Options: { closeOnBackdrop: true, onClose: fn }
   */
  DS.openModal = function openModal(root, opts) {
    opts = opts || {};
    if (!root) return null;
    root.hidden = false;
    root.classList.remove("is-closed");
    root.setAttribute("data-open", "1");
    lockScroll(true);
    var close = function () {
      DS.closeModal(root);
      if (typeof opts.onClose === "function") opts.onClose();
    };
    root._weosDsClose = close;
    if (opts.closeOnBackdrop !== false) {
      var backdrop = root.querySelector(".weos-ds-modal-backdrop");
      if (backdrop && !backdrop._weosDsBound) {
        backdrop.addEventListener("click", function () {
          if (root._weosDsClose) root._weosDsClose();
        });
        backdrop._weosDsBound = true;
      }
    }
    var closer = root.querySelector("[data-weos-ds-close]");
    if (closer && !closer._weosDsBound) {
      closer.addEventListener("click", function () {
        if (root._weosDsClose) root._weosDsClose();
      });
      closer._weosDsBound = true;
    }
    try {
      var focusable = root.querySelector(
        ".weos-ds-modal button, .weos-ds-modal [href], .weos-ds-modal input, .weos-ds-modal select, .weos-ds-modal textarea"
      );
      if (focusable) focusable.focus();
    } catch (e) {}
    return root;
  };

  DS.closeModal = function closeModal(root) {
    if (!root) return;
    root.hidden = true;
    root.classList.add("is-closed");
    root.removeAttribute("data-open");
    lockScroll(false);
  };

  /**
   * Open a side panel root (.weos-ds-sidepanel-root).
   * Options: { side: "right"|"left", closeOnBackdrop: true, onClose: fn }
   */
  DS.openSidePanel = function openSidePanel(root, opts) {
    opts = opts || {};
    if (!root) return null;
    if (opts.side) root.setAttribute("data-side", opts.side);
    root.hidden = false;
    root.classList.remove("is-closed");
    root.setAttribute("data-open", "1");
    lockScroll(true);
    var close = function () {
      DS.closeSidePanel(root);
      if (typeof opts.onClose === "function") opts.onClose();
    };
    root._weosDsClose = close;
    if (opts.closeOnBackdrop !== false) {
      var backdrop = root.querySelector(".weos-ds-sidepanel-backdrop");
      if (backdrop && !backdrop._weosDsBound) {
        backdrop.addEventListener("click", function () {
          if (root._weosDsClose) root._weosDsClose();
        });
        backdrop._weosDsBound = true;
      }
    }
    var closer = root.querySelector("[data-weos-ds-close]");
    if (closer && !closer._weosDsBound) {
      closer.addEventListener("click", function () {
        if (root._weosDsClose) root._weosDsClose();
      });
      closer._weosDsBound = true;
    }
    return root;
  };

  DS.closeSidePanel = function closeSidePanel(root) {
    if (!root) return;
    root.hidden = true;
    root.classList.add("is-closed");
    root.removeAttribute("data-open");
    lockScroll(false);
  };

  /**
   * Wire a tablist: root has .weos-ds-tabs + [role=tab]; panels [role=tabpanel][data-tab].
   */
  DS.bindTabs = function bindTabs(tablist, opts) {
    opts = opts || {};
    if (!tablist) return null;
    var tabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"], .weos-ds-tab'));
    if (!tabs.length) return null;
    var panelRoot = opts.panelRoot || tablist.parentElement || document;

    function activate(tab) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.classList.toggle("is-active", on);
        var id = t.getAttribute("data-tab") || t.getAttribute("aria-controls");
        if (!id) return;
        var panel =
          panelRoot.querySelector('.weos-ds-tabpanel[data-tab="' + id + '"]') ||
          panelRoot.querySelector("#" + id) ||
          document.getElementById(id);
        if (panel) {
          if (on) panel.removeAttribute("hidden");
          else panel.setAttribute("hidden", "");
        }
      });
      if (typeof opts.onChange === "function") opts.onChange(tab);
    }

    tabs.forEach(function (t) {
      if (t._weosDsBound) return;
      t.addEventListener("click", function () {
        activate(t);
      });
      t._weosDsBound = true;
    });

    var initial =
      tabs.filter(function (t) {
        return t.getAttribute("aria-selected") === "true" || t.classList.contains("is-active");
      })[0] || tabs[0];
    activate(initial);
    return { activate: activate, tabs: tabs };
  };

  /** Escape closes the topmost open DS overlay. */
  function onKey(ev) {
    if (ev.key !== "Escape") return;
    var open =
      document.querySelector('.weos-ds-modal-root[data-open="1"]') ||
      document.querySelector('.weos-ds-sidepanel-root[data-open="1"]');
    if (open && open._weosDsClose) open._weosDsClose();
  }

  if (!global._weosDsKeyBound) {
    document.addEventListener("keydown", onKey);
    global._weosDsKeyBound = true;
  }

  DS.$ = $;
  global.WEOSDesignSystem = DS;
})(typeof window !== "undefined" ? window : globalThis);
