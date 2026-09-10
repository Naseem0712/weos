/**
 * WEOS Universal Canvas — Selection (multi-select foundation via selectedIds[]).
 * Selection keys are stable elementId / assemblyId / connectionId — not DOM order.
 */
(function (global) {
  "use strict";

  function createSelection(opts) {
    opts = opts || {};
    var allowMulti = opts.allowMulti !== false;
    var selected = [];
    var kind = "none"; // element | assembly | connection | none
    var hoverId = null;
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
        mode: selected.length > 1 ? "multi" : "single",
        multiSelectReady: true,
        allowMulti: allowMulti,
        selectedIds: selected.slice(),
        selectedElementIds: selected.slice(), // back-compat
        primaryId: selected.length ? selected[0] : null,
        primaryElementId: selected.length ? selected[0] : null,
        kind: selected.length ? kind : "none",
        hoverId: hoverId,
      };
    }

    function select(id, additive, nextKind) {
      var sid = String(id || "");
      if (!sid) {
        clear();
        return snapshot();
      }
      kind = nextKind || "element";
      if (additive && allowMulti) {
        var i = selected.indexOf(sid);
        if (i >= 0) selected.splice(i, 1);
        else selected.push(sid);
      } else {
        selected = [sid];
      }
      emit();
      return snapshot();
    }

    function setIds(ids, nextKind) {
      selected = (ids || []).map(String).filter(Boolean);
      kind = selected.length ? nextKind || "element" : "none";
      emit();
      return snapshot();
    }

    function clear() {
      selected = [];
      kind = "none";
      emit();
      return snapshot();
    }

    function isSelected(id) {
      return selected.indexOf(String(id || "")) >= 0;
    }

    function setHover(id) {
      var next = id ? String(id) : null;
      if (hoverId === next) return snapshot();
      hoverId = next;
      emit();
      return snapshot();
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
      setIds: setIds,
      clear: clear,
      isSelected: isSelected,
      setHover: setHover,
      onChange: onChange,
      snapshot: snapshot,
    };
  }

  global.WEOSCanvas = global.WEOSCanvas || {};
  global.WEOSCanvas.selection = { create: createSelection };
})(typeof window !== "undefined" ? window : globalThis);
