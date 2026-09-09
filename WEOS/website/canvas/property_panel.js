/**
 * WEOS Contextual Property Panel (Batch 9).
 * ONE panel synced to selection by element/assembly/connection IDs.
 * When WEOS_UNIVERSAL_CANVAS ON: hide legacy rail/shower/vent/window tool stacks.
 * Saves via SQL APIs — never localStorage SoT.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      if (k === "className") n.className = attrs[k];
      else if (k === "text") n.textContent = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    if (html != null) n.innerHTML = html;
    return n;
  }

  function hideLegacyTools(on) {
    var root = document.getElementById("view-cart");
    if (root) {
      if (on) root.classList.add("uc-mode");
      else root.classList.remove("uc-mode");
    }
    ["railTools", "showerTools", "ventTools", "windowCartTools"].forEach(function (id) {
      var node = document.getElementById(id);
      if (!node) return;
      if (on) {
        node.setAttribute("data-uc-wrapped", "1");
        node.classList.add("uc-legacy-hidden");
      } else {
        node.removeAttribute("data-uc-wrapped");
        node.classList.remove("uc-legacy-hidden");
      }
    });
  }

  function createPanel(mountEl, options) {
    options = options || {};
    if (!mountEl) throw new Error("property panel mount required");

    var state = {
      kind: "none",
      elementId: null,
      assemblyId: null,
      connectionId: null,
      productType: null,
      schema: null,
      values: {},
      dirty: false,
      saving: false,
    };

    mountEl.classList.add("uc-property-panel");
    mountEl.innerHTML =
      '<div class="uc-pp-head"><strong>Properties</strong>' +
      '<span class="muted uc-pp-sel" style="margin-left:.5rem;font-size:.75rem">No selection</span></div>' +
      '<div class="uc-pp-body muted" style="font-size:.82rem;padding:.5rem 0">Select an element on the Engineering Canvas.</div>' +
      '<div class="uc-pp-status muted" style="font-size:.72rem;margin-top:.35rem"></div>' +
      '<div class="uc-pp-actions" style="margin-top:.5rem;display:none">' +
      '<button type="button" class="btn sm" data-pp="save">Save</button>' +
      '<button type="button" class="btn ghost sm" data-pp="reload">Reload</button></div>';

    var body = mountEl.querySelector(".uc-pp-body");
    var selLabel = mountEl.querySelector(".uc-pp-sel");
    var status = mountEl.querySelector(".uc-pp-status");
    var actions = mountEl.querySelector(".uc-pp-actions");
    var apiFn = options.api || (typeof global.api === "function" ? global.api : null);

    function setStatus(msg, isErr) {
      if (!status) return;
      status.textContent = msg || "";
      status.style.color = isErr ? "#a11" : "";
    }

    function collectForm() {
      var out = {};
      mountEl.querySelectorAll("[data-pp-key]").forEach(function (inp) {
        var key = inp.getAttribute("data-pp-key");
        var domain = inp.getAttribute("data-pp-domain") || "config";
        if (inp.type === "checkbox") out[key] = !!inp.checked;
        else if (inp.type === "number") out[key] = inp.value === "" ? null : Number(inp.value);
        else out[key] = inp.value;
        out["__domain_" + key] = domain;
      });
      return out;
    }

    function renderEmpty(guidance) {
      state.kind = "none";
      state.elementId = null;
      if (selLabel) selLabel.textContent = "No selection";
      body.className = "uc-pp-body muted";
      body.style.fontSize = ".82rem";
      body.textContent = (guidance && guidance.guidance) || "Select an element on the Engineering Canvas.";
      if (actions) actions.style.display = "none";
    }

    function renderPanel(payload) {
      payload = payload || {};
      state.kind = payload.kind || "none";
      state.schema = payload.schema || {};
      state.values = payload.values || {};
      var sel = payload.selection || {};
      state.elementId = sel.elementId || null;
      state.assemblyId = sel.assemblyId || null;
      state.connectionId = sel.connectionId || null;
      state.productType = sel.productType || state.values.productType || null;

      if (state.kind === "none") {
        renderEmpty(payload);
        return;
      }

      if (selLabel) {
        selLabel.textContent =
          (state.productType || state.kind) +
          (state.elementId ? " · " + state.elementId : "") +
          (state.assemblyId && state.kind === "assembly" ? " · " + state.assemblyId : "") +
          (state.connectionId ? " · " + state.connectionId : "");
      }

      body.className = "uc-pp-body";
      body.innerHTML = "";
      var groups = (state.schema && state.schema.groups) || [];
      groups.forEach(function (g) {
        var box = el("div", { className: "uc-pp-group" });
        box.appendChild(el("div", { className: "uc-pp-group-title", text: g.label || g.id || "" }));
        (g.fields || []).forEach(function (f) {
          var row = el("div", { className: "uc-pp-field" });
          row.appendChild(el("label", { className: "l", text: f.label || f.key }));
          var val = state.values[f.key];
          if (val == null) val = "";
          var input;
          if (f.type === "readonly" || f.type === "json") {
            input = el("div", {
              className: "muted",
              text: typeof val === "object" ? JSON.stringify(val) : String(val),
            });
          } else if (f.type === "boolean") {
            input = el("input", { type: "checkbox", "data-pp-key": f.key, "data-pp-domain": f.domain || "config" });
            input.checked = !!val;
          } else if (f.type === "number") {
            input = el("input", {
              type: "number",
              "data-pp-key": f.key,
              "data-pp-domain": f.domain || "config",
              value: val === "" || val == null ? "" : String(val),
            });
          } else {
            input = el("input", {
              type: "text",
              "data-pp-key": f.key,
              "data-pp-domain": f.domain || "config",
              value: String(val),
            });
          }
          if (input.tagName === "INPUT") {
            input.addEventListener("change", function () {
              state.dirty = true;
              setStatus("Unsaved changes", false);
            });
          }
          row.appendChild(input);
          box.appendChild(row);
        });
        body.appendChild(box);
      });
      if (actions) actions.style.display = state.kind === "element" ? "flex" : "none";
      setStatus("", false);
    }

    async function loadSelection(sel) {
      sel = sel || {};
      if (!apiFn) {
        renderEmpty({ guidance: "API unavailable for property panel." });
        return;
      }
      try {
        var kind = "none";
        var id = null;
        if (sel.elementId) {
          kind = "element";
          id = sel.elementId;
        } else if (sel.connectionId) {
          kind = "connection";
          id = sel.connectionId;
        } else if (sel.assemblyId) {
          kind = "assembly";
          id = sel.assemblyId;
        }
        var q = "/api/property-panel?kind=" + encodeURIComponent(kind);
        if (id) q += "&id=" + encodeURIComponent(id);
        var payload = await apiFn(q);
        renderPanel(payload);
      } catch (e) {
        setStatus("Failed to load properties: " + (e && e.message ? e.message : e), true);
      }
    }

    async function save() {
      if (state.kind !== "element" || !state.elementId || !apiFn) return;
      if (state.saving) return;
      state.saving = true;
      setStatus("Saving…", false);
      try {
        var form = collectForm();
        var patch = {};
        var config = {};
        Object.keys(form).forEach(function (k) {
          if (k.indexOf("__domain_") === 0) return;
          var domain = form["__domain_" + k] || "config";
          if (domain === "geometry" || domain === "identity") {
            if (domain === "geometry") patch[k] = form[k];
          } else {
            config[k] = form[k];
          }
        });
        patch.config = config;
        var res = await apiFn("/api/property-panel/element/" + encodeURIComponent(state.elementId), {
          method: "POST",
          body: patch,
        });
        if (!res || !res.persisted) {
          setStatus("Save failed — server did not confirm persistence.", true);
          if (typeof global.toast === "function") global.toast("Property save failed", true);
          return;
        }
        state.dirty = false;
        setStatus("Saved", false);
        if (typeof global.toast === "function") global.toast("Properties saved");
        renderPanel(
          Object.assign({}, { kind: "element", schema: state.schema, values: res.element, selection: res.selection })
        );
        if (typeof options.onSaved === "function") options.onSaved(res);
      } catch (e) {
        setStatus("Save failed: " + (e && e.message ? e.message : e), true);
        if (typeof global.toast === "function") global.toast("Property save failed", true);
      } finally {
        state.saving = false;
      }
    }

    mountEl.querySelector('[data-pp="save"]').onclick = function () {
      save();
    };
    mountEl.querySelector('[data-pp="reload"]').onclick = function () {
      loadSelection({
        elementId: state.elementId,
        assemblyId: state.assemblyId,
        connectionId: state.connectionId,
      });
    };

    return {
      loadSelection: loadSelection,
      renderPanel: renderPanel,
      hideLegacyTools: hideLegacyTools,
      getState: function () {
        return {
          kind: state.kind,
          elementId: state.elementId,
          assemblyId: state.assemblyId,
          connectionId: state.connectionId,
          productType: state.productType,
        };
      },
      save: save,
    };
  }

  function tryMount(host, options) {
    options = options || {};
    if (!options.enabled) {
      hideLegacyTools(false);
      return null;
    }
    hideLegacyTools(true);
    var mount =
      document.getElementById("ucPropertyPanel") ||
      (function () {
        var preview = document.querySelector(".cart-preview");
        if (!preview) return null;
        var box = el("div", { id: "ucPropertyPanel" });
        preview.appendChild(box);
        return box;
      })();
    if (!mount) return null;
    var panel = createPanel(mount, options);
    if (host && typeof host.onSelect === "function") {
      host.onSelect(function (selected) {
        panel.loadSelection(selected || {});
      });
    }
    panel.loadSelection(null);
    return panel;
  }

  C.propertyPanel = { createPanel: createPanel, tryMount: tryMount, hideLegacyTools: hideLegacyTools };
})(typeof window !== "undefined" ? window : globalThis);
