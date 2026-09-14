/**
 * WEOS Engineering BOM viewer — outside canvas.
 * Design Card "View BOM" opens this panel. CURRENT/STALE + regenerate.
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

  function statusBadge(status, freshness) {
    var s = freshness === "STALE" || status === "STALE" ? "STALE" : status || "—";
    var cls = "eng-bom__badge eng-bom__badge--" + String(s).toLowerCase();
    return '<span class="' + cls + '">' + esc(s) + "</span>";
  }

  function renderBom(bom) {
    var lines = bom.lines || [];
    var issues = bom.issues || [];
    var sum = bom.summary || {};
    var rows = lines
      .map(function (ln) {
        return (
          "<tr>" +
          "<td>" +
          esc(ln.category) +
          "</td><td>" +
          esc(ln.code || "") +
          "</td><td>" +
          esc(ln.description) +
          "</td><td>" +
          esc(ln.profileRole || "") +
          "</td><td>" +
          esc(ln.quantity) +
          "</td><td>" +
          esc(ln.unit) +
          "</td><td>" +
          esc(ln.requiredLengthMm != null ? Math.round(ln.requiredLengthMm) : "") +
          "</td><td>" +
          esc(ln.stockConsumptionMm != null ? Math.round(ln.stockConsumptionMm) : "") +
          "</td><td>" +
          esc(ln.weightKg != null ? Number(ln.weightKg).toFixed(3) : "") +
          "</td><td>" +
          esc(ln.areaSqm != null ? Number(ln.areaSqm).toFixed(4) : "") +
          "</td><td>" +
          esc(ln.deductionMode || "") +
          "</td></tr>"
        );
      })
      .join("");
    var issueHtml = issues.length
      ? '<ul class="eng-bom__issues">' +
        issues
          .map(function (i) {
            return (
              "<li class=\"eng-bom__issue eng-bom__issue--" +
              esc(i.severity || "info") +
              '">[' +
              esc(i.code || "") +
              "] " +
              esc(i.message || "") +
              "</li>"
            );
          })
          .join("") +
        "</ul>"
      : "";
    return (
      '<div class="eng-bom" data-batch="ENG-BOM" data-element-id="' +
      esc(bom.elementId || "") +
      '">' +
      '<div class="eng-bom__head">' +
      "<div><strong>Engineering BOM</strong> " +
      statusBadge(bom.status, bom.freshness) +
      '<p class="muted" style="margin:.2rem 0 0;font-size:.8rem">Derived from design + masters — not quote selling rates. Generator ' +
      esc(bom.generatorVersion || "") +
      "</p></div>" +
      '<div class="eng-bom__actions">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnEngBomRegen">Regenerate</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnEngBomClose">Close</button>' +
      "</div></div>" +
      '<div class="eng-bom__meta muted">' +
      "Lines " +
      esc(sum.lineCount || lines.length) +
      " · Weight " +
      esc(sum.totalWeightKg != null ? sum.totalWeightKg + " kg" : "—") +
      " · Glass " +
      esc(sum.totalGlassAreaSqm != null ? sum.totalGlassAreaSqm + " m²" : "—") +
      " · Master " +
      esc(bom.masterRevisionToken || "—") +
      (bom.staleReason ? " · Stale: " + esc(bom.staleReason) : "") +
      "</div>" +
      issueHtml +
      '<div class="eng-bom__table-wrap"><table class="eng-bom__table"><thead><tr>' +
      "<th>Cat</th><th>Code</th><th>Description</th><th>Role</th><th>Qty</th><th>Unit</th>" +
      "<th>Req mm</th><th>Stock mm</th><th>kg</th><th>m²</th><th>Deduction</th>" +
      "</tr></thead><tbody>" +
      (rows || '<tr><td colspan="11" class="muted">No lines</td></tr>') +
      "</tbody></table></div></div>"
    );
  }

  async function openForElement(host, elementId) {
    if (!host || !elementId) return;
    host.classList.remove("hidden");
    host.innerHTML = '<p class="muted">Loading BOM…</p>';
    try {
      var bom;
      try {
        bom = await api("/api/elements/" + encodeURIComponent(elementId) + "/bom");
      } catch (e) {
        bom = await api("/api/elements/" + encodeURIComponent(elementId) + "/bom/generate", {
          method: "POST",
          body: "{}",
        });
      }
      host.innerHTML = renderBom(bom);
      bind(host, elementId);
    } catch (err) {
      host.innerHTML =
        '<div class="eng-bom"><p class="err">' +
        esc(err.message || err) +
        '</p><button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnEngBomClose">Close</button></div>';
      bind(host, elementId);
    }
  }

  function bind(host, elementId) {
    var close = host.querySelector("#btnEngBomClose");
    if (close)
      close.onclick = function () {
        host.classList.add("hidden");
        host.innerHTML = "";
      };
    var regen = host.querySelector("#btnEngBomRegen");
    if (regen)
      regen.onclick = async function () {
        regen.disabled = true;
        try {
          var bom = await api(
            "/api/elements/" + encodeURIComponent(elementId) + "/bom/regenerate",
            { method: "POST", body: "{}" }
          );
          host.innerHTML = renderBom(bom);
          bind(host, elementId);
        } catch (err) {
          global.alert(err.message || String(err));
          regen.disabled = false;
        }
      };
  }

  C.engineeringBom = {
    openForElement: openForElement,
    renderBom: renderBom,
  };
})(typeof window !== "undefined" ? window : globalThis);
