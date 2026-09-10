/**
 * WEOS Canvas D2 — Duplicate design modal (multi-size rows → real new IDs).
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

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
      "<strong>Duplicate design</strong>" +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-qw-dup-close>Close</button>' +
      "</div>" +
      '<p class="muted" style="margin:.35rem 0 .6rem;font-size:.78rem">Creates new quote items with new IDs. Config/description/specs inherit; geometry regenerates at each size (not an SVG clone).</p>' +
      '<div class="muted" id="qwDupSource" style="font-size:.75rem;margin-bottom:.5rem"></div>' +
      '<div class="qw-dup-table-wrap"><table class="qw-dup-table"><thead><tr>' +
      "<th>W mm</th><th>H mm</th><th>Qty</th><th>Floor</th><th>Location</th><th>Mark</th><th>Rate</th><th></th>" +
      "</tr></thead><tbody id=\"qwDupBody\"></tbody></table></div>" +
      '<div class="qw-dup-modal__foot">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwDupAddRow">+ Size row</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnQwDupCreateAll">Create All</button>' +
      "</div>" +
      '<div class="err" id="qwDupErr" style="margin-top:.4rem;font-size:.78rem"></div>' +
      "</div>";
    global.document.body.appendChild(modal);
    return modal;
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
      '<td><input data-f="floor" type="text" value="' +
      esc(row.floor || "") +
      '"/></td>' +
      '<td><input data-f="location" type="text" value="' +
      esc(row.location || "") +
      '"/></td>' +
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
        } else {
          obj[f] = v;
        }
      });
      rows.push(obj);
    });
    return rows;
  }

  function openDuplicateModal(opts) {
    opts = opts || {};
    var modal = ensureModal();
    modal.dataset.lineId = opts.lineId || "";
    modal.dataset.projectId = opts.projectId || "";
    var src = global.document.getElementById("qwDupSource");
    if (src) {
      src.textContent =
        "Source ID " +
        (opts.lineId || "—") +
        (opts.displayName ? " · " + opts.displayName : "") +
        (opts.widthMm && opts.heightMm
          ? " · " + Math.round(opts.widthMm) + "×" + Math.round(opts.heightMm) + " mm"
          : "");
    }
    var body = global.document.getElementById("qwDupBody");
    if (body) {
      body.innerHTML = rowHtml({
        width: opts.widthMm,
        height: opts.heightMm,
        qty: opts.qty || 1,
        floor: opts.floor || "",
        location: opts.location || "",
        mark: opts.mark || "",
        sellingRate: opts.sellingRate,
      });
    }
    var err = global.document.getElementById("qwDupErr");
    if (err) err.textContent = "";
    modal.classList.remove("hidden");
    wireOnce();
  }

  function closeDuplicateModal() {
    var modal = global.document.getElementById("qwDupModal");
    if (modal) modal.classList.add("hidden");
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
    var create = global.document.getElementById("btnQwDupCreateAll");
    if (create) {
      create.onclick = async function () {
        var err = global.document.getElementById("qwDupErr");
        if (err) err.textContent = "";
        var body = global.document.getElementById("qwDupBody");
        var rows = collectRows(body);
        var lineId = modal.dataset.lineId;
        var projectId = modal.dataset.projectId;
        if (!projectId || !lineId) {
          if (err) err.textContent = "Missing project or design id";
          return;
        }
        if (!rows.length) {
          if (err) err.textContent = "Add at least one size row";
          return;
        }
        try {
          create.disabled = true;
          var api = typeof global.api === "function" ? global.api : null;
          if (!api) throw new Error("API unavailable");
          var res = await api("/api/projects/" + encodeURIComponent(projectId) + "/designs/" + encodeURIComponent(lineId) + "/duplicate", {
            method: "POST",
            body: { rows: rows },
          });
          if (!res || !res.persisted) throw new Error("Server did not confirm durable duplicate");
          closeDuplicateModal();
          if (C.quoteWorkspace && C.quoteWorkspace.onDuplicated) {
            C.quoteWorkspace.onDuplicated(res);
          } else if (typeof global.toast === "function") {
            global.toast("Created " + (res.createdCount || 0) + " design(s)");
          }
        } catch (e) {
          if (err) err.textContent = (e && e.message) || String(e);
        } finally {
          create.disabled = false;
        }
      };
    }
  }

  C.designDuplicate = {
    open: openDuplicateModal,
    close: closeDuplicateModal,
    collectRows: collectRows,
    ensureModal: ensureModal,
  };
})(typeof window !== "undefined" ? window : globalThis);
