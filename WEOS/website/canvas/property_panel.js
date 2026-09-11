/**
 * WEOS Contextual Property Panel (Batch 9 + Canvas D4).
 * ONE panel synced to selection by element/assembly/connection IDs.
 * Authoritative pipeline: field → validate → GEOMETRY|CONFIG →
 *   local upsert OR SQL save → DesignElement → adapter preview → UC → Saved.
 * Never uses hidden legacy Window Cart as source of truth.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  var GEOM_KEYS = {
    widthMm: 1,
    heightMm: 1,
    depthMm: 1,
    xMm: 1,
    yMm: 1,
    orientation: 1,
    sillHeightMm: 1,
  };

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
    try {
      if (C.workspace && C.workspace.applyPrimaryCutover) {
        C.workspace.applyPrimaryCutover(!!on);
      }
    } catch (eCut) {}
    try {
      if (C.designContext && C.designContext.getActive) {
        C.designContext.getActive().routeLegacyIntoUc();
      }
    } catch (e) {}
  }

  function fieldMeta(f) {
    f = f || {};
    var domain = String(f.domain || (GEOM_KEYS[f.key] ? "geometry" : "config"));
    var updateTarget =
      f.updateTarget ||
      (domain === "geometry" || domain === "identity" ? "GEOMETRY" : "CONFIG");
    var editable = f.editable !== false && f.type !== "readonly" && f.type !== "json";
    var supported = f.supported !== false;
    var disabledReason =
      f.disabledReason ||
      (!supported
        ? "Not supported for this product"
        : !editable
          ? "Read-only"
          : "");
    return {
      key: f.key,
      label: f.label || f.key,
      type: f.type || "string",
      domain: domain,
      updateTarget: updateTarget,
      editable: editable && supported,
      supported: supported,
      disabledReason: disabledReason,
      options: f.options || null,
      min: f.min,
      max: f.max,
    };
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
      selection: null,
      dirty: false,
      saving: false,
      commitGen: 0,
      _collapsePref: {},
      _bindAbort: null,
      _debounceTimers: {},
      _pendingCommitKeys: null,
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

    function setHostSave(statusKind, detail) {
      try {
        var host = global.WEOS_UNIVERSAL_CANVAS_HOST;
        if (host && typeof host.setSaveStatus === "function") {
          host.setSaveStatus(statusKind, detail || "");
        }
      } catch (e) {}
    }

    function getDc() {
      return (
        global.WEOS_DESIGN_CONTEXT ||
        (C.designContext && C.designContext.getActive && C.designContext.getActive({ api: apiFn }))
      );
    }

    function isLocalId(id) {
      return !!(id && String(id).indexOf("local-") === 0);
    }

    function collectForm() {
      var out = {};
      mountEl.querySelectorAll("[data-pp-key]").forEach(function (inp) {
        var key = inp.getAttribute("data-pp-key");
        var domain = inp.getAttribute("data-pp-domain") || "config";
        var target = inp.getAttribute("data-pp-target") || "CONFIG";
        if (inp.disabled) return;
        if (inp.type === "checkbox") out[key] = !!inp.checked;
        else if (inp.type === "number") out[key] = inp.value === "" ? null : Number(inp.value);
        else out[key] = inp.value;
        out["__domain_" + key] = domain;
        out["__target_" + key] = target;
      });
      return out;
    }

    function readInputValue(input) {
      if (!input) return null;
      if (input.type === "checkbox") return !!input.checked;
      if (input.type === "number") {
        if (input.value === "") return null;
        var n = Number(input.value);
        return isFinite(n) ? n : null;
      }
      return input.value;
    }

    function validateField(meta, value) {
      if (!meta || !meta.editable) {
        return { ok: false, error: (meta && meta.disabledReason) || "Field not editable" };
      }
      if (meta.type === "number") {
        if (value == null || value === "") {
          return { ok: false, error: (meta.label || meta.key) + " required" };
        }
        var n = Number(value);
        if (!isFinite(n)) {
          return { ok: false, error: (meta.label || meta.key) + " must be a number" };
        }
        if (meta.min != null && n < Number(meta.min)) {
          return { ok: false, error: (meta.label || meta.key) + " below minimum" };
        }
        if (meta.max != null && n > Number(meta.max)) {
          return { ok: false, error: (meta.label || meta.key) + " above maximum" };
        }
        if (GEOM_KEYS[meta.key] && (meta.key === "widthMm" || meta.key === "heightMm" || meta.key === "depthMm") && n <= 0) {
          return { ok: false, error: (meta.label || meta.key) + " must be > 0" };
        }
        return { ok: true, value: n };
      }
      if (meta.type === "boolean") {
        return { ok: true, value: !!value };
      }
      return { ok: true, value: value };
    }

    function abortBindings() {
      if (state._bindAbort && typeof state._bindAbort.abort === "function") {
        try {
          state._bindAbort.abort();
        } catch (e) {}
      }
      state._bindAbort =
        typeof AbortController !== "undefined"
          ? new AbortController()
          : { aborted: false, signal: { aborted: false }, abort: function () { this.aborted = true; this.signal.aborted = true; } };
      Object.keys(state._debounceTimers || {}).forEach(function (k) {
        clearTimeout(state._debounceTimers[k]);
      });
      state._debounceTimers = {};
    }

    function syncQuoteCard(element, previewSvg) {
      try {
        if (C.quoteWorkspace && typeof C.quoteWorkspace.syncCardFromElement === "function") {
          C.quoteWorkspace.syncCardFromElement(element, previewSvg);
        }
      } catch (eSync) {}
    }

    function applyLocalGeometry(patch) {
      var host = global.WEOS_UNIVERSAL_CANVAS_HOST;
      if (!host || !state.elementId) return null;
      var cur =
        (host.getViewModel &&
          (host.getViewModel().elements || []).filter(function (e) {
            return e.elementId === state.elementId;
          })[0]) ||
        {};
      var next = Object.assign({}, cur, {
        elementId: state.elementId,
        productType: state.productType || cur.productType,
        displayCode: cur.displayCode || state.values.displayCode || state.elementId,
        widthMm: patch.widthMm != null ? patch.widthMm : cur.widthMm != null ? cur.widthMm : state.values.widthMm,
        heightMm: patch.heightMm != null ? patch.heightMm : cur.heightMm != null ? cur.heightMm : state.values.heightMm,
        xMm: patch.xMm != null ? patch.xMm : cur.xMm != null ? cur.xMm : state.values.xMm || 0,
        yMm: patch.yMm != null ? patch.yMm : cur.yMm != null ? cur.yMm : state.values.yMm || 0,
        configPayload: Object.assign({}, cur.configPayload || {}, state.values || {}, patch.config || {}),
      });
      if (patch.depthMm != null) {
        next.heightMm = patch.depthMm;
        next.configPayload.depthMm = patch.depthMm;
      }
      if (typeof host.applyElementPatch === "function") {
        return host.applyElementPatch(state.elementId, next);
      }
      if (typeof host.upsertLocalElement === "function") {
        return host.upsertLocalElement(next);
      }
      return next;
    }

    /**
     * Authoritative single-field (or batch) commit.
     * Property Panel → validate → GEOMETRY|CONFIG → save → DesignElement → preview → UC.
     */
    async function commitUpdate(patchKeys, opts) {
      opts = opts || {};
      if (state.kind !== "element" || !state.elementId) {
        setStatus("No element selected", true);
        return { ok: false, error: "no element" };
      }

      var form = collectForm();
      var geom = {};
      var config = {};
      var keys = patchKeys && patchKeys.length ? patchKeys : Object.keys(form).filter(function (k) {
        return k.indexOf("__") !== 0;
      });

      // D4: if a save is in flight, queue latest keys — commitGen provides latest-wins.
      if (state.saving && !opts.allowParallel && !opts.fromQueue) {
        state._pendingCommitKeys = keys.slice();
        return { ok: false, error: "busy", queued: true };
      }

      for (var i = 0; i < keys.length; i++) {
        var key = keys[i];
        if (!key || key.indexOf("__") === 0) continue;
        var meta = null;
        var groups = (state.schema && state.schema.groups) || [];
        for (var g = 0; g < groups.length; g++) {
          var fields = groups[g].fields || [];
          for (var fi = 0; fi < fields.length; fi++) {
            if (fields[fi].key === key) {
              meta = fieldMeta(fields[fi]);
              break;
            }
          }
          if (meta) break;
        }
        if (!meta) {
          meta = fieldMeta({
            key: key,
            domain: form["__domain_" + key] || (GEOM_KEYS[key] ? "geometry" : "config"),
            type: typeof form[key] === "number" ? "number" : typeof form[key] === "boolean" ? "boolean" : "string",
          });
        }
        var raw = form[key];
        var v = validateField(meta, raw);
        if (!v.ok) {
          setStatus(v.error, true);
          setHostSave("error", v.error);
          return { ok: false, error: v.error };
        }
        var target = meta.updateTarget || form["__target_" + key] || "CONFIG";
        if (target === "GEOMETRY" || meta.domain === "geometry") {
          geom[key] = v.value;
        } else if (meta.domain === "identity") {
          /* identity not written */
        } else {
          config[key] = v.value;
        }
      }

      state.commitGen += 1;
      var gen = state.commitGen;
      state.saving = true;
      state.dirty = true;
      setStatus("Saving…", false);
      setHostSave("saving", "Property update");

      var mergedValues = Object.assign({}, state.values, geom, config);
      if (geom.depthMm != null && geom.heightMm == null) {
        mergedValues.heightMm = geom.depthMm;
      }
      state.values = mergedValues;

      var dc = getDc();
      if (dc && typeof dc.applyConfigPatch === "function") {
        dc.applyConfigPatch(Object.assign({}, geom, config), {
          elementId: state.elementId,
          productType: state.productType,
        });
      }

      try {
        // Local drafts — never hit SQL element endpoints.
        if (isLocalId(state.elementId)) {
          var localEl = applyLocalGeometry(Object.assign({}, geom, { config: config }));
          if (dc && typeof dc.refreshElementPreview === "function") {
            await dc.refreshElementPreview(
              {
                elementId: state.elementId,
                productType: state.productType,
                widthMm: mergedValues.widthMm,
                heightMm: mergedValues.heightMm,
                displayCode: localEl && localEl.displayCode,
              },
              mergedValues
            );
          }
          if (gen !== state.commitGen) {
            return { ok: false, stale: true };
          }
          state.dirty = true;
          state.saving = false;
          setStatus("Updated (local draft)", false);
          setHostSave("unsaved", "Local draft — Add to Quote to persist");
          syncQuoteCard(
            Object.assign({}, localEl || {}, {
              widthMm: mergedValues.widthMm,
              heightMm: mergedValues.heightMm,
              productType: state.productType,
            }),
            null
          );
          if (typeof options.onCommitted === "function") {
            options.onCommitted({ local: true, element: localEl, values: mergedValues });
          }
          return { ok: true, local: true, element: localEl };
        }

        if (!apiFn) {
          setStatus("API unavailable — cannot save", true);
          setHostSave("error", "API unavailable");
          state.saving = false;
          return { ok: false, error: "no api" };
        }

        var body = Object.assign({}, geom, { config: config });
        var res = await apiFn("/api/property-panel/element/" + encodeURIComponent(state.elementId), {
          method: "POST",
          body: body,
        });

        if (gen !== state.commitGen) {
          return { ok: false, stale: true };
        }

        if (!res || !res.persisted) {
          setStatus("Save failed — server did not confirm persistence.", true);
          setHostSave("error", "Save rejected");
          if (typeof global.toast === "function") global.toast("Property save failed", true);
          state.saving = false;
          return { ok: false, error: "not persisted" };
        }

        var elOut = res.element || {};
        state.values = Object.assign({}, state.values, elOut, elOut.configPayload || {});
        state.dirty = false;
        state.saving = false;
        setStatus("Saved", false);
        setHostSave("saved", "SQL persisted");

        var host = global.WEOS_UNIVERSAL_CANVAS_HOST;
        if (host && typeof host.applyElementPatch === "function") {
          host.applyElementPatch(state.elementId, {
            elementId: elOut.elementId || state.elementId,
            productType: elOut.productType || state.productType,
            displayCode: elOut.displayCode,
            widthMm: elOut.widthMm,
            heightMm: elOut.heightMm,
            xMm: elOut.xMm,
            yMm: elOut.yMm,
            configPayload: elOut.configPayload || {},
            assemblyId: elOut.assemblyId,
          });
        }

        var svg = res.preview && res.preview.svg ? res.preview.svg : null;
        if (svg && host && typeof host.setElementPreviewSvg === "function") {
          host.setElementPreviewSvg(state.elementId, svg, { source: "adapter" });
        } else if (dc && typeof dc.refreshElementPreview === "function") {
          await dc.refreshElementPreview(
            {
              elementId: state.elementId,
              productType: state.productType || elOut.productType,
              widthMm: elOut.widthMm,
              heightMm: elOut.heightMm,
              displayCode: elOut.displayCode,
            },
            Object.assign({}, elOut.configPayload || {}, state.values)
          );
        }

        syncQuoteCard(elOut, svg);
        if (typeof options.onSaved === "function") options.onSaved(res);
        if (typeof options.onCommitted === "function") options.onCommitted(res);
        return { ok: true, persisted: true, element: elOut, res: res };
      } catch (e) {
        if (gen !== state.commitGen) return { ok: false, stale: true };
        var msg = e && e.message ? e.message : String(e);
        setStatus("Save failed: " + msg, true);
        setHostSave("error", msg);
        if (typeof global.toast === "function") global.toast("Property save failed", true);
        state.saving = false;
        return { ok: false, error: msg };
      } finally {
        if (gen === state.commitGen) {
          state.saving = false;
          if (state._pendingCommitKeys && state._pendingCommitKeys.length) {
            var pending = state._pendingCommitKeys;
            state._pendingCommitKeys = null;
            commitUpdate(pending, { fromQueue: true, allowParallel: true });
          }
        }
      }
    }

    function scheduleCommit(key, meta) {
      if (!meta || !meta.editable) return;
      clearTimeout(state._debounceTimers[key]);
      if (meta.type === "number") {
        state._debounceTimers[key] = setTimeout(function () {
          commitUpdate([key]);
        }, 280);
      } else {
        commitUpdate([key]);
      }
    }

    function wireField(input, meta) {
      if (!input || !meta) return;
      var signal = state._bindAbort && state._bindAbort.signal;
      var opts = signal ? { signal: signal } : undefined;

      function onCommitEvent() {
        if (!meta.editable) return;
        state.dirty = true;
        setStatus("Unsaved changes", false);
        if (meta.type === "number") {
          scheduleCommit(meta.key, meta);
        } else {
          commitUpdate([meta.key]);
        }
      }

      if (meta.type === "number") {
        input.addEventListener(
          "input",
          function () {
            state.dirty = true;
            setStatus("Unsaved changes", false);
            scheduleCommit(meta.key, meta);
          },
          opts
        );
        input.addEventListener(
          "blur",
          function () {
            clearTimeout(state._debounceTimers[meta.key]);
            commitUpdate([meta.key]);
          },
          opts
        );
        input.addEventListener(
          "change",
          function () {
            clearTimeout(state._debounceTimers[meta.key]);
            commitUpdate([meta.key]);
          },
          opts
        );
      } else if (meta.type === "boolean" || input.tagName === "SELECT") {
        input.addEventListener("change", onCommitEvent, opts);
      } else {
        input.addEventListener("change", onCommitEvent, opts);
        input.addEventListener(
          "blur",
          function () {
            if (state.dirty) commitUpdate([meta.key]);
          },
          opts
        );
      }
    }

    function renderEmpty(guidance) {
      abortBindings();
      state.kind = "none";
      state.elementId = null;
      state.selection = null;
      if (selLabel) selLabel.textContent = "No selection";
      body.className = "uc-pp-body muted";
      body.style.fontSize = ".82rem";
      var msg =
        (guidance && (guidance.guidance || guidance.message)) ||
        (typeof guidance === "string" ? guidance : null) ||
        "Select an element on the Engineering Canvas.";
      body.textContent = msg;
      if (actions) actions.style.display = "none";
    }

    function renderPanel(payload) {
      payload = payload || {};
      abortBindings();
      state.kind = payload.kind || "none";
      state.schema = payload.schema || {};
      state.values = payload.values || {};
      var sel = payload.selection || {};
      state.selection = sel;
      state.elementId = sel.elementId || state.values.elementId || null;
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
      var collapsePref = state._collapsePref || (state._collapsePref = {});
      var groups = (state.schema && state.schema.groups) || [];
      groups.forEach(function (g) {
        var gid = String(g.id || g.label || "group");
        var box = el("div", { className: "weos-ds-prop-section uc-pp-group" });
        if (collapsePref[gid]) box.classList.add("is-collapsed");
        var head = el("div", { className: "weos-ds-prop-section__head" });
        head.appendChild(el("span", { text: g.label || g.id || "" }));
        head.appendChild(el("span", { className: "weos-ds-prop-section__chevron", "aria-hidden": "true" }));
        head.addEventListener("click", function () {
          box.classList.toggle("is-collapsed");
          collapsePref[gid] = box.classList.contains("is-collapsed");
        });
        box.appendChild(head);
        var sectBody = el("div", { className: "weos-ds-prop-section__body" });
        (g.fields || []).forEach(function (f) {
          var meta = fieldMeta(f);
          var row = el("div", { className: "uc-pp-field" });
          row.appendChild(el("label", { className: "l", text: meta.label }));
          var val = state.values[meta.key];
          if (val == null) val = "";
          var input;
          if (!meta.editable) {
            input = el("div", {
              className: "muted",
              text: typeof val === "object" ? JSON.stringify(val) : String(val),
            });
            if (meta.disabledReason) {
              input.title = meta.disabledReason;
              row.appendChild(
                el("div", {
                  className: "muted",
                  text: meta.disabledReason,
                })
              );
            }
            row.setAttribute("data-pp-readonly", "1");
          } else if (meta.type === "boolean") {
            input = el("input", {
              type: "checkbox",
              className: "weos-ds-input",
              "data-pp-key": meta.key,
              "data-pp-domain": meta.domain,
              "data-pp-target": meta.updateTarget,
            });
            input.checked = !!val;
          } else if (meta.options && meta.options.length) {
            input = el("select", {
              className: "weos-ds-select weos-ds-input",
              "data-pp-key": meta.key,
              "data-pp-domain": meta.domain,
              "data-pp-target": meta.updateTarget,
            });
            meta.options.forEach(function (opt) {
              var o = el("option", {
                value: String(opt.value != null ? opt.value : opt),
                text: String(opt.label != null ? opt.label : opt),
              });
              if (String(val) === o.value) o.selected = true;
              input.appendChild(o);
            });
          } else if (meta.type === "number") {
            input = el("input", {
              type: "number",
              className: "weos-ds-input",
              "data-pp-key": meta.key,
              "data-pp-domain": meta.domain,
              "data-pp-target": meta.updateTarget,
              value: val === "" || val == null ? "" : String(val),
            });
            if (meta.min != null) input.min = String(meta.min);
            if (meta.max != null) input.max = String(meta.max);
          } else {
            input = el("input", {
              type: "text",
              className: "weos-ds-input",
              "data-pp-key": meta.key,
              "data-pp-domain": meta.domain,
              "data-pp-target": meta.updateTarget,
              value: String(val),
            });
          }
          if (input && (input.tagName === "INPUT" || input.tagName === "SELECT") && meta.editable) {
            wireField(input, meta);
          }
          row.appendChild(input);
          row.setAttribute("data-pp-update-target", meta.updateTarget);
          sectBody.appendChild(row);
        });
        box.appendChild(sectBody);
        body.appendChild(box);
      });
      if (actions) actions.style.display = state.kind === "element" ? "flex" : "none";
      setStatus("", false);
    }

    async function loadSelection(sel) {
      sel = sel || {};
      if (!sel.elementId && !sel.connectionId && !sel.assemblyId && !sel.productType) {
        renderEmpty();
        return;
      }
      if (sel.elementId && isLocalId(sel.elementId)) {
        try {
          var ptLocal = sel.productType;
          if (!ptLocal && global.WEOS_DESIGN_CONTEXT) {
            ptLocal = (global.WEOS_DESIGN_CONTEXT.get() || {}).selectedProductType;
          }
          if (ptLocal && apiFn) {
            var schemaLocal = await apiFn("/api/adapters/" + encodeURIComponent(ptLocal) + "/schema");
            renderPanel({
              kind: "element",
              schema: schemaLocal,
              values: Object.assign(
                {
                  productType: ptLocal,
                  elementId: sel.elementId,
                  widthMm: sel.widthMm,
                  heightMm: sel.heightMm,
                  xMm: sel.xMm,
                  yMm: sel.yMm,
                },
                sel.configPayload || {}
              ),
              selection: {
                kind: "element",
                elementId: sel.elementId,
                productType: ptLocal,
              },
            });
            return;
          }
        } catch (eLocal) {}
        if (global.WEOS_DESIGN_CONTEXT && global.WEOS_DESIGN_CONTEXT.refreshPropertyPanel) {
          global.WEOS_DESIGN_CONTEXT.refreshPropertyPanel();
          return;
        }
      }
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
        try {
          var pt = sel.productType;
          if (pt) {
            var schema = await apiFn("/api/adapters/" + encodeURIComponent(pt) + "/schema");
            renderPanel({
              kind: "element",
              schema: schema,
              values: {
                productType: pt,
                elementId: sel.elementId || null,
                widthMm: sel.widthMm,
                heightMm: sel.heightMm,
              },
              selection: { kind: "element", elementId: sel.elementId || null, productType: pt },
            });
            return;
          }
        } catch (e2) {}
        setStatus("Failed to load properties: " + (e && e.message ? e.message : e), true);
      }
    }

    async function save() {
      return commitUpdate(null, { allowParallel: false });
    }

    mountEl.querySelector('[data-pp="save"]').onclick = function () {
      save();
    };
    mountEl.querySelector('[data-pp="reload"]').onclick = function () {
      loadSelection({
        elementId: state.elementId,
        assemblyId: state.assemblyId,
        connectionId: state.connectionId,
        productType: state.productType,
      });
    };

    return {
      loadSelection: loadSelection,
      renderPanel: renderPanel,
      hideLegacyTools: hideLegacyTools,
      commitUpdate: commitUpdate,
      getState: function () {
        return {
          kind: state.kind,
          elementId: state.elementId,
          assemblyId: state.assemblyId,
          connectionId: state.connectionId,
          productType: state.productType,
          dirty: state.dirty,
          saving: state.saving,
          commitGen: state.commitGen,
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
      (host && host.propertyPanelEl) ||
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
        try {
          if (C.designContext && C.designContext.getActive) {
            var dc = C.designContext.getActive({ api: options.api });
            if (selected && selected.elementId) {
              dc.selectElement(selected);
            } else {
              dc.switchProduct({ productType: null, source: "clear-selection", forceClear: true });
            }
          }
        } catch (e) {}
        panel.loadSelection(selected || {});
      });
    }
    panel.loadSelection(null);
    return panel;
  }

  C.propertyPanel = {
    createPanel: createPanel,
    tryMount: tryMount,
    hideLegacyTools: hideLegacyTools,
    fieldMeta: fieldMeta,
  };
})(typeof window !== "undefined" ? window : globalThis);
