/**
 * WEOS Canvas Batch D — Command state + domain history (not DOM clones).
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  var TOOLS = {
    SELECT: "select",
    PAN: "pan",
    MEASURE: "measure",
    MEMBER: "member",
    MEMBER_V: "member_v",
    MEMBER_H: "member_h",
    GRID: "grid_split",
  };
  var ACTIVE = [TOOLS.SELECT, TOOLS.PAN, TOOLS.MEASURE];
  var RESERVED = [TOOLS.MEMBER, TOOLS.MEMBER_V, TOOLS.MEMBER_H, TOOLS.GRID];
  var ZOOM_MIN = 0.15;
  var ZOOM_MAX = 6;

  function clampZoom(z) {
    var n = Number(z);
    if (!isFinite(n) || n <= 0) n = 1;
    return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(n * 100) / 100));
  }

  function createCommandState(opts) {
    opts = opts || {};
    var tool = String(opts.activeTool || TOOLS.SELECT).toLowerCase();
    if (ACTIVE.indexOf(tool) < 0 && RESERVED.indexOf(tool) < 0) tool = TOOLS.SELECT;
    var ids = (opts.selectedIds || []).map(String).filter(Boolean);
    return {
      batch: "CANVAS-D",
      activeTool: tool,
      canUndo: !!opts.canUndo,
      canRedo: !!opts.canRedo,
      selection: {
        selectedIds: ids.slice(),
        primaryId: ids.length ? ids[0] : null,
        kind: ids.length ? opts.kind || "element" : "none",
      },
      zoom: clampZoom(opts.zoom == null ? 1 : opts.zoom),
      saveStatus: opts.saveStatus || "local",
      gridVisible: opts.gridVisible !== false,
      snapEnabled: opts.snapEnabled !== false,
      cursor: { xMm: null, yMm: null },
      deleteEnabled: false,
    };
  }

  function setActiveTool(state, tool) {
    var t = String(tool || TOOLS.SELECT).toLowerCase();
    if (RESERVED.indexOf(t) >= 0) return state;
    if (ACTIVE.indexOf(t) < 0) t = TOOLS.SELECT;
    state.activeTool = t;
    return state;
  }

  function createHistory(opts) {
    opts = opts || {};
    var max = Math.max(1, Number(opts.maxSize) || 50);
    var undoStack = [];
    var redoStack = [];
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
        canUndo: undoStack.length > 0,
        canRedo: redoStack.length > 0,
        undoDepth: undoStack.length,
        redoDepth: redoStack.length,
        maxSize: max,
      };
    }

    function push(cmd) {
      cmd = cmd || {};
      var entry = {
        id: cmd.id || "cmd-" + (undoStack.length + 1),
        type: String(cmd.type || "noop"),
        payload: cmd.payload ? JSON.parse(JSON.stringify(cmd.payload)) : {},
        before: cmd.before != null ? JSON.parse(JSON.stringify(cmd.before)) : null,
        after: cmd.after != null ? JSON.parse(JSON.stringify(cmd.after)) : null,
        timestamp: cmd.timestamp != null ? cmd.timestamp : Date.now(),
      };
      undoStack.push(entry);
      if (undoStack.length > max) undoStack = undoStack.slice(-max);
      redoStack = [];
      emit();
      return entry;
    }

    function undo() {
      if (!undoStack.length) return null;
      var cmd = undoStack.pop();
      redoStack.push(cmd);
      emit();
      return cmd;
    }

    function redo() {
      if (!redoStack.length) return null;
      var cmd = redoStack.pop();
      undoStack.push(cmd);
      emit();
      return cmd;
    }

    return {
      push: push,
      undo: undo,
      redo: redo,
      snapshot: snapshot,
      onChange: function (fn) {
        if (typeof fn === "function") listeners.push(fn);
      },
      get canUndo() {
        return undoStack.length > 0;
      },
      get canRedo() {
        return redoStack.length > 0;
      },
    };
  }

  function saveStatusFromDurable(flags) {
    flags = flags || {};
    if (flags.error) return "error";
    if (flags.saving) return "saving";
    if (flags.localOnly) return "local";
    if (flags.persisted === true && flags.durable === true) return "saved";
    if (flags.persisted === false || flags.durable === false) return "error";
    return "unsaved";
  }

  function keyboardShortcutAllowed(target) {
    if (!target) return true;
    if (target.isContentEditable) return false;
    var tag = String(target.tagName || "").toLowerCase();
    return tag !== "input" && tag !== "textarea" && tag !== "select";
  }

  C.commands = {
    TOOLS: TOOLS,
    ACTIVE_TOOLS: ACTIVE,
    RESERVED_TOOLS: RESERVED,
    ZOOM_MIN: ZOOM_MIN,
    ZOOM_MAX: ZOOM_MAX,
    clampZoom: clampZoom,
    createCommandState: createCommandState,
    setActiveTool: setActiveTool,
    createHistory: createHistory,
    saveStatusFromDurable: saveStatusFromDurable,
    keyboardShortcutAllowed: keyboardShortcutAllowed,
  };
})(typeof window !== "undefined" ? window : globalThis);
