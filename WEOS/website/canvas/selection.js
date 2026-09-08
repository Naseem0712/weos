/**
 * WEOS Universal Canvas — Selection (single-select now, multi-select-ready).
 * Selection keys are stable elementId values from the scene — not DOM order.
 */
(function (global) {
  "use strict";

  function createSelection(opts) {
    opts = opts || {};
    var selected = [];
    var listeners = [];

    function emit() {
      var snap = snapshot();
      listeners.forEach(function (fn) {
        try {
          fn(snap);
        } catch (e) {}
      });
    }

    function snapshot() {
      return {
        mode: "single",
        multiSelectReady: true,
        selectedElementIds: selected.slice(),
        primaryElementId: selected.length ? selected[0] : null,
      };
    }

    function select(elementId, additive) {
      var id = String(elementId || "");
      if (!id) {
        clear();
        return snapshot();
      }
      if (additive && opts.allowMulti) {
        var i = selected.indexOf(id);
        if (i >= 0) selected.splice(i, 1);
        else selected.push(id);
      } else {
        selected = [id];
      }
      emit();
      return snapshot();
    }

    function clear() {
      selected = [];
      emit();
      return snapshot();
    }

    function isSelected(elementId) {
      return selected.indexOf(String(elementId || "")) >= 0;
    }

    function onChange(fn) {
      if (typeof fn === "function") listeners.push(fn);
      return function () {
        listeners = listeners.filter(function (f) {
          return f !== fn;
        });
      };
    }

    return {
      select: select,
      clear: clear,
      isSelected: isSelected,
      onChange: onChange,
      snapshot: snapshot,
    };
  }

  global.WEOSCanvas = global.WEOSCanvas || {};
  global.WEOSCanvas.selection = { create: createSelection };
})(typeof window !== "undefined" ? window : globalThis);
