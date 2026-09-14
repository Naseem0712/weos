/**
 * WEOS Canvas G — Duplicate design modal (multi-size + KEEP_OFFSETS|SCALE).
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});
  var _floors = [];
  var _creating = false;
  var _idempotencyKey = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  function ensureModal() {
    var existing = global.document.getElementById("qwDupModal");
    if (existing) return existing;
    var modal = global.document.createElement("div");
    modal.id = "qwDupModal";
    modal.className = "qw-dup-modal hidden";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", "Duplicate design");
    modal.innerHTML =
      '<div class="qw-dup-modal__panel weos-ds-surface">' +
      '<div class="qw-dup-modal__head">' +
      "<strong id=\"qwDupTitle\">Duplicate design</strong>" +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-qw-dup-close>Close</button>' +
      "</div>" +
      '<p class="muted" style="margin:.35rem 0 .4rem;font-size:.78rem">Creates new designs with new IDs. Topology, assignments, config, description/specs inherit. Different sizes require an explicit structural rule.</p>' +
      '<div class="muted" id="qwDupSource" style="font-size:.75rem;margin-bottom:.45rem"></div>' +
      '<div class="qw-dup-rule" id="qwDupRuleBox" style="margin-bottom:.5rem">' +
      '<span class="muted" style="font-size:.75rem">Structural layout (when size differs):</span> ' +
      '<label style="margin-right:.75rem;font-size:.78rem"><input type="radio" name="qwDupRule" value="KEEP_OFFSETS"/> Keep member offsets</label>' +
      '<label style="font-size:.78rem"><input type="radio" name="qwDupRule" value="SCALE"/> Scale layout proportionally</label>' +
      "</div>" +
      '<div class="qw-dup-table-wrap"><table class="qw-dup-table"><thead><tr>' +
      "<th>W mm</th><th>H mm</th><th>Qty</th><th>Floor</th><th>Location</th><th>Mark</th><th>Rate</th><th></th>" +
      "</tr></thead><tbody id=\"qwDupBody\"></tbody></table></div>" +
      '<div id="qwDupRowStatus" class="muted" style="font-size:.75rem;margin-top:.35rem"></div>' +
      '<div class="qw-dup-modal__foot">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwDupAddRow">+ Add Row</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwDupSameRate">Apply Same Rate</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwDupSameFloor">Apply Same Floor</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwDupSameLoc">Apply Same Location</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnQwDupCreateAll">Create All</button>' +
      "</div>" +
      '<div class="err" id="qwDupErr" style="margin-top:.4rem;font-size:.78rem"></div>' +
      "</div>";
    global.document.body.appendChild(modal);
    return modal;
  }

  function floorOptions(selectedId, selectedName) {
    var html = '<option value="">—</option>';
    (_floors || []).forEach(function (f) {
      var id = f.floorId || f.id || "";
      var name = f.name || f.displayName || id;
      var sel = id === selectedId || name === selectedName ? " selected" : "";
      html += '<option value="' + esc(id) + '" data-name="' + esc(name) + '"' + sel + ">" + esc(name) + "</option>";
    });
    return html;
  }

  function locOptions(floorId, selectedId, selectedName) {
    var html = '<option value="">—</option>';
    var floor = (_floors || []).find(function (f) {
      return String(f.floorId || f.id) === String(floorId);
    });
    var locs = (floor && (floor.locations || floor.locs)) || [];
    locs.forEach(function (l) {
      var id = l.locationId || l.id || "";
      var name = l.name || l.displayName || id;
      var sel = id === selectedId || name === selectedName ? " selected" : "";
      html += '<option value="' + esc(id) + '" data-name="' + esc(name) + '"' + sel + ">" + esc(name) + "</option>";
    });
    return html;
  }

  function rowHtml(row) {
    row = row || {};
    return (
      "<tr>" +
      '<td><input data-f="width" type="number" value="' +
      esc(row.width || row.widthMm || "") +
      '"/></td>' +
      '<td><input data-f="height" type="number" value="' +
      esc(row.height || row.heightMm || "") +
      '"/></td>' +
      '<td><input data-f="qty" type="number" value="' +
      esc(row.qty != null ? row.qty : 1) +
      '"/></td>' +
      '<td><select data-f="floorId">' +
      floorOptions(row.floorId, row.floor) +
      "</select></td>" +
      '<td><select data-f="locationId">' +
      locOptions(row.floorId, row.locationId, row.location) +
      "</select></td>" +
      '<td><input data-f="mark" type="text" value="' +
      esc(row.mark || "") +
      '"/></td>' +
      '<td><input data-f="sellingRate" type="number" value="' +
      esc(row.sellingRate != null ? row.sellingRate : row.rate || "") +
      '"/></td>' +
      '<td><button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-qw-dup-del>✕</button></td>' +
      "</tr>"
    );
  }

  function collectRows(tbody) {
    var rows = [];
    if (!tbody) return rows;
    tbody.querySelectorAll("tr").forEach(function (tr) {
      var obj = {};
      tr.querySelectorAll("[data-f]").forEach(function (inp) {
        var f = inp.getAttribute("data-f");
        var v = inp.value;
        if (f === "width" || f === "height" || f === "qty" || f === "sellingRate") {
          obj[f] = v === "" ? null : Number(v);
        } else if (f === "floorId" || f === "locationId") {
          obj[f] = v || null;
          var opt = inp.options && inp.options[inp.selectedIndex];
          if (opt) {
            if (f === "floorId") obj.floor = opt.getAttribute("data-name") || opt.textContent;
            if (f === "locationId") obj.location = opt.getAttribute("data-name") || opt.textContent;
          }
        } else {
          obj[f] = v;
        }
      });
      rows.push(obj);
    });
    return rows;
  }

  function selectedRule() {
    var radios = global.document.querySelectorAll('input[name="qwDupRule"]');
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) return radios[i].value;
    }
    return null;
  }

  async function loadFloors(projectId) {
    _floors = [];
    if (!projectId || typeof global.api !== "function") return;
    try {
      var res = await global.api("/api/projects/" + encodeURIComponent(projectId) + "/floors");
      var list = (res && (res.floors || res.items)) || [];
      // Enrich with locations
      var out = [];
      for (var i = 0; i < list.length; i++) {
        var f = list[i];
        var locs = f.locations || [];
        if (!locs.length && f.floorId) {
          try {
            var lr = await global.api("/api/floors/" + encodeURIComponent(f.floorId) + "/locations");
            locs = (lr && (lr.locations || lr.items)) || [];
          } catch (_) {}
        }
        f.locations = locs;
        out.push(f);
      }
      _floors = out;
    } catch (_) {
      _floors = [];
    }
  }

  function openDuplicateModal(opts) {
    opts = opts || {};
    var modal = ensureModal();
    modal.dataset.lineId = opts.lineId || "";
    modal.dataset.projectId = opts.projectId || "";
    modal.dataset.srcW = String(opts.widthMm || "");
    modal.dataset.srcH = String(opts.heightMm || "");
    modal.dataset.isComposite = opts.isComposite ? "1" : "0";
    _idempotencyKey = "DUP-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
    _creating = false;
    var title = global.document.getElementById("qwDupTitle");
    if (title) title.textContent = "Duplicate " + (opts.mark || opts.lineId || "design");
    var src = global.document.getElementById("qwDupSource");
    if (src) {
      src.textContent =
        (opts.displayName || "Design") +
        " · ID " +
        (opts.lineId || "—") +
        (opts.widthMm && opts.heightMm
          ? " · " + Math.round(opts.widthMm) + "×" + Math.round(opts.heightMm) + " mm"
          : "") +
        (opts.composition ? " · " + opts.composition : "");
    }
    // Clear rule selection — never silent default when both valid
    global.document.querySelectorAll('input[name="qwDupRule"]').forEach(function (r) {
      r.checked = false;
    });
    var status = global.document.getElementById("qwDupRowStatus");
    if (status) status.textContent = "";
    loadFloors(opts.projectId).then(function () {
      var body = global.document.getElementById("qwDupBody");
      if (body) {
        body.innerHTML = rowHtml({
          width: opts.widthMm,
          height: opts.heightMm,
          qty: opts.qty || 1,
          floor: opts.floor || "",
          location: opts.location || "",
          floorId: opts.floorId || "",
          locationId: opts.locationId || "",
          mark: opts.mark || "",
          sellingRate: opts.sellingRate,
        });
      }
    });
    var err = global.document.getElementById("qwDupErr");
    if (err) err.textContent = "";
    modal.classList.remove("hidden");
    wireOnce();
  }

  function closeDuplicateModal() {
    var modal = global.document.getElementById("qwDupModal");
    if (modal) modal.classList.add("hidden");
    _creating = false;
  }

  function applyFirstField(field) {
    var body = global.document.getElementById("qwDupBody");
    if (!body) return;
    var rows = body.querySelectorAll("tr");
    if (!rows.length) return;
    var first = rows[0].querySelector('[data-f="' + field + '"]');
    if (!first) return;
    var val = first.value;
    rows.forEach(function (tr, i) {
      if (i === 0) return;
      var inp = tr.querySelector('[data-f="' + field + '"]');
      if (inp) {
        inp.value = val;
        if (field === "floorId" && inp.onchange) inp.onchange();
        // refresh locations when floor applied
        if (field === "floorId") {
          var loc = tr.querySelector('[data-f="locationId"]');
          if (loc) loc.innerHTML = locOptions(val, "", "");
        }
      }
    });
  }

  function wireOnce() {
    var modal = ensureModal();
    if (modal._qwWired) return;
    modal._qwWired = true;
    modal.addEventListener("click", function (ev) {
      var t = ev.target;
      if (t === modal || (t && t.getAttribute && t.getAttribute("data-qw-dup-close") != null)) {
        closeDuplicateModal();
        return;
      }
      if (t && t.getAttribute && t.getAttribute("data-qw-dup-del") != null) {
        var tr = t.closest("tr");
        var body = global.document.getElementById("qwDupBody");
        if (tr && body && body.querySelectorAll("tr").length > 1) tr.remove();
      }
    });
    modal.addEventListener("change", function (ev) {
      var t = ev.target;
      if (t && t.getAttribute && t.getAttribute("data-f") === "floorId") {
        var tr = t.closest("tr");
        if (!tr) return;
        var loc = tr.querySelector('[data-f="locationId"]');
        if (loc) loc.innerHTML = locOptions(t.value, "", "");
      }
    });
    var add = global.document.getElementById("btnQwDupAddRow");
    if (add) {
      add.onclick = function () {
        var body = global.document.getElementById("qwDupBody");
        if (!body) return;
        var last = body.querySelector("tr:last-child");
        var seed = {};
        if (last) {
          last.querySelectorAll("[data-f]").forEach(function (inp) {
            seed[inp.getAttribute("data-f")] = inp.value;
          });
        }
        body.insertAdjacentHTML("beforeend", rowHtml(seed));
      };
    }
    var sameRate = global.document.getElementById("btnQwDupSameRate");
    if (sameRate) sameRate.onclick = function () {
      applyFirstField("sellingRate");
    };
    var sameFloor = global.document.getElementById("btnQwDupSameFloor");
    if (sameFloor) sameFloor.onclick = function () {
      applyFirstField("floorId");
    };
    var sameLoc = global.document.getElementById("btnQwDupSameLoc");
    if (sameLoc) sameLoc.onclick = function () {
      applyFirstField("locationId");
    };
    var create = global.document.getElementById("btnQwDupCreateAll");
    if (create) {
      create.onclick = async function () {
        if (_creating) return;
        var err = global.document.getElementById("qwDupErr");
        var statusEl = global.document.getElementById("qwDupRowStatus");
        if (err) err.textContent = "";
        if (statusEl) statusEl.textContent = "";
        var body = global.document.getElementById("qwDupBody");
        var rows = collectRows(body);
        var lineId = modal.dataset.lineId;
        var projectId = modal.dataset.projectId;
        var srcW = Number(modal.dataset.srcW) || 0;
        var srcH = Number(modal.dataset.srcH) || 0;
        if (!projectId || !lineId) {
          if (err) err.textContent = "Missing project or design id";
          return;
        }
        if (!rows.length) {
          if (err) err.textContent = "Add at least one size row";
          return;
        }
        var rule = selectedRule();
        var needsRule = rows.some(function (r) {
          var w = Number(r.width) || 0;
          var h = Number(r.height) || 0;
          return Math.abs(w - srcW) > 0.5 || Math.abs(h - srcH) > 0.5;
        });
        if (needsRule && !rule) {
          if (err) err.textContent = "Choose Keep offsets or Scale when sizes differ — never silent guess.";
          return;
        }
        rows = rows.map(function (r) {
          var w = Number(r.width) || 0;
          var h = Number(r.height) || 0;
          var differ = Math.abs(w - srcW) > 0.5 || Math.abs(h - srcH) > 0.5;
          if (differ && rule) r.sizeChangeRule = rule;
          return r;
        });
        try {
          _creating = true;
          create.disabled = true;
          var api = typeof global.api === "function" ? global.api : null;
          if (!api) throw new Error("API unavailable");
          var res = await api(
            "/api/projects/" +
              encodeURIComponent(projectId) +
              "/designs/" +
              encodeURIComponent(lineId) +
              "/duplicate",
            {
              method: "POST",
              body: { rows: rows, idempotencyKey: _idempotencyKey },
            }
          );
          if (!res || !res.persisted) throw new Error("Server did not confirm durable duplicate");
          var results = res.rowResults || [];
          if (statusEl && results.length) {
            statusEl.innerHTML = results
              .map(function (r) {
                return (
                  "Row " +
                  (r.index + 1) +
                  ": " +
                  esc(r.status) +
                  (r.reason ? " — " + esc(r.reason) : "") +
                  (r.lineId ? " (" + esc(r.lineId) + ")" : "")
                );
              })
              .join("<br/>");
          }
          if ((res.failedCount || 0) > 0 && (res.createdCount || 0) === 0) {
            if (err) err.textContent = "All rows failed — see status.";
            return;
          }
          closeDuplicateModal();
          if (C.quoteWorkspace && C.quoteWorkspace.onDuplicated) {
            C.quoteWorkspace.onDuplicated(res);
          } else if (typeof global.toast === "function") {
            global.toast("Created " + (res.createdCount || 0) + " design(s)");
          }
        } catch (e) {
          if (err) err.textContent = (e && e.message) || String(e);
        } finally {
          _creating = false;
          create.disabled = false;
        }
      };
    }
  }

  C.designDuplicate = {
    open: openDuplicateModal,
    close: closeDuplicateModal,
  };
})(typeof window !== "undefined" ? window : globalThis);
