/**
 * WEOS Engineering Costing + Selling Price workspace — outside canvas.
 * Tabs: Summary / Materials / Labour / Other / Selling.
 * Cost/profit admin-only; design card shows selling publicly.
 */
(function (global) {
  "use strict";
  var C = (global.WEOSCanvas = global.WEOSCanvas || {});

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function money(n) {
    var v = Number(n);
    if (!isFinite(v)) return "—";
    return "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }

  function sessionHeaders() {
    var h = { Accept: "application/json", "Content-Type": "application/json" };
    try {
      var tok =
        (global.WEOS && global.WEOS.sessionToken) ||
        global.localStorage.getItem("weos_session") ||
        "";
      if (tok) h["X-WEOS-Session"] = tok;
    } catch (e) {}
    return h;
  }

  function gstQ() {
    try {
      var g = (global.WEOS && global.WEOS.companyGst) || global.localStorage.getItem("weos_gst") || "";
      return g ? "?gst=" + encodeURIComponent(g) : "";
    } catch (e) {
      return "";
    }
  }

  function isAdmin() {
    try {
      if (global.WEOS && global.WEOS.isAdmin === true) return true;
      if (global.WEOS && global.WEOS.role === "admin") return true;
      var r = global.localStorage.getItem("weos_role") || "";
      return r === "admin" || r === "owner";
    } catch (e) {
      return true; // company session defaults to internal workspace
    }
  }

  async function api(path, opts) {
    var q = path.indexOf("?") >= 0 ? "" : gstQ();
    var res = await fetch(path + q, Object.assign({ headers: sessionHeaders() }, opts || {}));
    var data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = { detail: res.statusText };
    }
    if (!res.ok) throw new Error((data && (data.detail || data.message)) || res.statusText);
    return data;
  }

  function ensureHost() {
    var host = document.getElementById("engCostHost");
    if (!host) {
      host = document.createElement("div");
      host.id = "engCostHost";
      host.className = "eng-cost-host hidden";
      document.body.appendChild(host);
    }
    return host;
  }

  function badge(status, freshness) {
    var s = freshness === "STALE" || status === "STALE" ? "STALE" : status || "—";
    return '<span class="eng-cost__badge eng-cost__badge--' + esc(String(s).toLowerCase()) + '">' + esc(s) + "</span>";
  }

  function breakdownRows(totals) {
    var t = totals || {};
    var keys = [
      "MATERIAL",
      "GLASS",
      "HARDWARE",
      "ACCESSORIES",
      "COATING",
      "FABRICATION",
      "INSTALLATION",
      "TRANSPORT",
      "WASTAGE",
      "OVERHEAD",
      "OTHER",
    ];
    return keys
      .map(function (k) {
        return (
          "<tr><td>" +
          esc(k) +
          "</td><td>" +
          money(t[k] || 0) +
          "</td></tr>"
        );
      })
      .join("");
  }

  function materialRows(lines) {
    return (lines || [])
      .filter(function (ln) {
        return ["MATERIAL", "GLASS", "HARDWARE", "ACCESSORIES"].indexOf(ln.breakdownCategory) >= 0;
      })
      .map(function (ln) {
        return (
          "<tr>" +
          "<td>" +
          esc(ln.breakdownCategory) +
          "</td><td>" +
          esc(ln.code || "") +
          "</td><td>" +
          esc(ln.description) +
          "</td><td>" +
          esc(ln.quantityBasis != null ? Number(ln.quantityBasis).toFixed(4) : "") +
          "</td><td>" +
          esc(ln.quantityUnit || "") +
          "</td><td>" +
          money(ln.unitCost) +
          "</td><td>" +
          money(ln.extendedCost) +
          "</td><td>" +
          esc(ln.precisionMode || "") +
          "</td></tr>"
        );
      })
      .join("");
  }

  function labourRows(lines) {
    return (lines || [])
      .filter(function (ln) {
        return ["FABRICATION", "INSTALLATION", "COATING"].indexOf(ln.breakdownCategory) >= 0;
      })
      .map(function (ln) {
        return (
          "<tr><td>" +
          esc(ln.breakdownCategory) +
          "</td><td>" +
          esc(ln.description) +
          "</td><td>" +
          money(ln.extendedCost) +
          "</td></tr>"
        );
      })
      .join("");
  }

  function otherRows(lines) {
    return (lines || [])
      .filter(function (ln) {
        return ["TRANSPORT", "WASTAGE", "OVERHEAD", "OTHER"].indexOf(ln.breakdownCategory) >= 0;
      })
      .map(function (ln) {
        return (
          "<tr><td>" +
          esc(ln.breakdownCategory) +
          "</td><td>" +
          esc(ln.description) +
          "</td><td>" +
          money(ln.extendedCost) +
          "</td></tr>"
        );
      })
      .join("");
  }

  function renderPanel(costing, tab) {
    var admin = isAdmin();
    var t = tab || "summary";
    var sell = costing.selling || {};
    var body = "";
    if (t === "summary") {
      body =
        (admin
          ? '<table class="eng-cost__table"><thead><tr><th>Category</th><th>Amount</th></tr></thead><tbody>' +
            breakdownRows(costing.categoryTotals) +
            '<tr><th>TOTAL COST</th><th>' +
            money(costing.totalCost) +
            "</th></tr></tbody></table>"
          : '<p class="muted">Cost breakdown is admin-only.</p>') +
        '<div class="eng-cost__sell-box">' +
        "<div><span class=\"muted\">Suggested</span><strong> " +
        money(costing.suggestedSelling) +
        "</strong></div>" +
        "<div><span class=\"muted\">Actual selling</span><strong> " +
        money(costing.actualSelling) +
        "</strong></div>" +
        (admin
          ? "<div><span class=\"muted\">Gross profit</span><strong> " +
            money(costing.grossProfit) +
            "</strong> (" +
            esc(costing.grossMarginPct != null ? Number(costing.grossMarginPct).toFixed(2) + "%" : "—") +
            ")</div>"
          : "") +
        "</div>";
    } else if (t === "materials") {
      body = admin
        ? '<div class="eng-cost__table-wrap"><table class="eng-cost__table"><thead><tr><th>Cat</th><th>Code</th><th>Desc</th><th>Qty</th><th>Unit</th><th>Rate</th><th>Ext</th><th>Prec</th></tr></thead><tbody>' +
          materialRows(costing.lines) +
          "</tbody></table></div>"
        : '<p class="muted">Materials cost is admin-only.</p>';
    } else if (t === "labour") {
      body = admin
        ? '<table class="eng-cost__table"><thead><tr><th>Cat</th><th>Desc</th><th>Ext</th></tr></thead><tbody>' +
          labourRows(costing.lines) +
          "</tbody></table>"
        : '<p class="muted">Labour cost is admin-only.</p>';
    } else if (t === "other") {
      body = admin
        ? '<table class="eng-cost__table"><thead><tr><th>Cat</th><th>Desc</th><th>Ext</th></tr></thead><tbody>' +
          otherRows(costing.lines) +
          "</tbody></table>"
        : '<p class="muted">Other costs are admin-only.</p>';
    } else if (t === "selling") {
      body =
        '<form id="engCostSellForm" class="eng-cost__form">' +
        '<label>Method <select name="method">' +
        ["COST_PLUS_MARKUP", "COST_PLUS_TARGET_MARGIN", "MANUAL_RATE", "MANUAL_AMOUNT", "UNIT_RATE", "LEGACY_MANUAL_RATE"]
          .map(function (m) {
            return (
              '<option value="' +
              m +
              '"' +
              (costing.sellingMethod === m ? " selected" : "") +
              ">" +
              m +
              "</option>"
            );
          })
          .join("") +
        "</select></label>" +
        '<label>Markup % <input name="markupPct" type="number" step="0.01" value="' +
        esc(costing.markupPct != null ? costing.markupPct : 25) +
        '"/></label>' +
        '<label>Target margin % <input name="targetMarginPct" type="number" step="0.01" value="' +
        esc(costing.targetMarginPct != null ? costing.targetMarginPct : "") +
        '"/></label>' +
        '<label>Commercial unit <input name="commercialUnit" value="' +
        esc(costing.commercialUnit || "SFT") +
        '"/></label>' +
        '<label>Billing qty override <input name="billingQtyOverride" type="number" step="0.001" value="' +
        esc(costing.billingQtyOverride != null ? costing.billingQtyOverride : "") +
        '"/></label>' +
        '<p class="muted" style="font-size:.78rem">Calculated qty: ' +
        esc(costing.calculatedQty) +
        " · Billing qty: " +
        esc(costing.billingQty) +
        " (override does not change geometry)</p>" +
        '<button type="submit" class="weos-ds-btn weos-ds-btn--sm">Save selling</button>' +
        "</form>" +
        (admin
          ? '<p class="muted" style="margin-top:.6rem">Cost unchanged by selling edits: ' +
            money(costing.totalCost) +
            "</p>"
          : "");
    }

    return (
      '<div class="eng-cost" data-batch="ENG-COST" data-element-id="' +
      esc(costing.elementId || "") +
      '" data-costing-id="' +
      esc(costing.costingId || "") +
      '">' +
      '<div class="eng-cost__head">' +
      "<div><strong>Engineering Costing</strong> " +
      badge(costing.calcStatus || costing.status, costing.freshness) +
      '<p class="muted" style="margin:.2rem 0 0;font-size:.8rem">BOM-derived cost · selling separate · not on customer PDF. ' +
      esc(costing.generatorVersion || "") +
      "</p></div>" +
      '<div class="eng-cost__actions">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnEngCostRegen">Regenerate</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnEngCostClose">Close</button>' +
      "</div></div>" +
      '<div class="eng-cost__tabs">' +
      ["summary", "materials", "labour", "other", "selling"]
        .map(function (name) {
          return (
            '<button type="button" class="eng-cost__tab' +
            (t === name ? " is-active" : "") +
            '" data-eng-cost-tab="' +
            name +
            '">' +
            name[0].toUpperCase() +
            name.slice(1) +
            "</button>"
          );
        })
        .join("") +
      "</div>" +
      '<div class="eng-cost__body">' +
      body +
      "</div></div>"
    );
  }

  async function openForElement(elementId, opts) {
    var host = ensureHost();
    host.classList.remove("hidden");
    host.innerHTML = '<p class="muted">Loading costing…</p>';
    var tab = (opts && opts.tab) || "summary";
    try {
      var costing;
      try {
        costing = await api("/api/elements/" + encodeURIComponent(elementId) + "/costing");
      } catch (e) {
        costing = await api("/api/elements/" + encodeURIComponent(elementId) + "/costing/generate", {
          method: "POST",
          body: JSON.stringify({ method: "COST_PLUS_MARKUP", markupPct: 25 }),
        });
      }
      host._costing = costing;
      host._tab = tab;
      host.innerHTML = renderPanel(costing, tab);
      bind(host, elementId);
    } catch (err) {
      host.innerHTML =
        '<div class="eng-cost"><p class="eng-cost__err">' +
        esc(err.message || err) +
        '</p><button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnEngCostClose">Close</button></div>';
      host.querySelector("#btnEngCostClose").onclick = function () {
        host.classList.add("hidden");
      };
    }
  }

  function bind(host, elementId) {
    var close = host.querySelector("#btnEngCostClose");
    if (close)
      close.onclick = function () {
        host.classList.add("hidden");
      };
    var regen = host.querySelector("#btnEngCostRegen");
    if (regen)
      regen.onclick = async function () {
        host.innerHTML = '<p class="muted">Regenerating…</p>';
        var costing = await api(
          "/api/elements/" + encodeURIComponent(elementId) + "/costing/regenerate",
          { method: "POST", body: "{}" }
        );
        host._costing = costing;
        host.innerHTML = renderPanel(costing, host._tab || "summary");
        bind(host, elementId);
      };
    host.querySelectorAll("[data-eng-cost-tab]").forEach(function (btn) {
      btn.onclick = function () {
        host._tab = btn.getAttribute("data-eng-cost-tab");
        host.innerHTML = renderPanel(host._costing, host._tab);
        bind(host, elementId);
      };
    });
    var form = host.querySelector("#engCostSellForm");
    if (form) {
      form.onsubmit = async function (ev) {
        ev.preventDefault();
        var fd = new FormData(form);
        var body = {};
        fd.forEach(function (v, k) {
          if (v === "") return;
          body[k] = k.indexOf("Pct") >= 0 || k.indexOf("Qty") >= 0 || k.indexOf("Rate") >= 0 || k.indexOf("Amount") >= 0
            ? Number(v)
            : v;
        });
        var updated = await api(
          "/api/costing/" + encodeURIComponent(host._costing.costingId) + "/selling",
          { method: "POST", body: JSON.stringify(body) }
        );
        host._costing = updated;
        host.innerHTML = renderPanel(updated, "selling");
        bind(host, elementId);
      };
    }
  }

  C.openEngineeringCosting = openForElement;
  C.engineeringCosting = { open: openForElement, isAdmin: isAdmin };
})(typeof window !== "undefined" ? window : globalThis);
