/**
 * WEOS Canvas D2/G — Quote Review design cards (authoritative saved data).
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function money(n) {
    var v = Number(n);
    if (!Number.isFinite(v)) return "₹ —";
    try {
      return "₹ " + v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
    } catch (_) {
      return "₹ " + Math.round(v);
    }
  }

  function sizeLabel(card) {
    var w = Number(card.widthMm) || 0;
    var h = Number(card.heightMm) || 0;
    if (w <= 0 && h <= 0) return "—";
    return Math.round(w) + "×" + Math.round(h) + " mm";
  }

  function statusLabel(st) {
    var m = {
      ready: "Ready",
      incomplete: "Incomplete",
      drawing_issue: "Drawing issue",
      missing_rate: "Missing rate",
      incomplete_drawing: "Drawing issue",
      needs_data: "Incomplete",
    };
    return m[st] || st || "Ready";
  }

  function renderCard(card) {
    var warn =
      (card.warnings || []).length > 0
        ? '<ul class="qw-card__warn">' +
          (card.warnings || [])
            .slice(0, 3)
            .map(function (w) {
              return "<li>" + esc(w) + "</li>";
            })
            .join("") +
          "</ul>"
        : "";
    var preview = card.previewSvg
      ? '<div class="qw-card__preview" aria-hidden="true">' + card.previewSvg + "</div>"
      : '<div class="qw-card__preview qw-card__preview--empty muted">No saved preview</div>';
    var mark = card.mark ? esc(card.mark) : esc(card.lineId);
    var composition = card.composition || card.compositionSummary || "";
    return (
      '<article class="weos-ds-card qw-card" data-line-id="' +
      esc(card.lineId) +
      '" data-status="' +
      esc(card.status || "") +
      '" data-product-type="' +
      esc(card.productType || "") +
      '" data-floor="' +
      esc(card.floor || "") +
      '" data-location="' +
      esc(card.location || "") +
      '">' +
      '<div class="qw-card__top">' +
      '<div><span class="weos-ds-card__k">ID</span><div class="qw-card__id">' +
      mark +
      "</div></div>" +
      '<span class="qw-pill qw-pill--' +
      esc(card.status || "ready") +
      '">' +
      esc(statusLabel(card.status)) +
      "</span>" +
      "</div>" +
      preview +
      "<strong class=\"qw-card__title\">" +
      esc(card.displayName || card.product || "Design") +
      "</strong>" +
      (composition
        ? '<div class="qw-card__composition muted">' + esc(composition) + "</div>"
        : "") +
      '<div class="qw-card__meta muted">' +
      esc(sizeLabel(card)) +
      " · Qty " +
      esc(card.qty) +
      (card.floor ? " · " + esc(card.floor) : "") +
      (card.location ? " · " + esc(card.location) : "") +
      "</div>" +
      '<div class="qw-card__specs muted">' +
      (card.series ? "Series " + esc(card.series) + " · " : "") +
      money(card.sellingRate) +
      "/" +
      esc(card.saleUnit || "sqft") +
      "</div>" +
      '<div class="qw-card__amount">' +
      money(card.amount) +
      "</div>" +
      warn +
      '<div class="qw-card__actions">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-qw-edit="' +
      esc(card.lineId) +
      '">Edit</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-qw-dup="' +
      esc(card.lineId) +
      '">Duplicate</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-qw-del="' +
      esc(card.lineId) +
      '">Delete</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-qw-tpl="' +
      esc(card.lineId) +
      '" title="Save as Template">Template</button>' +
      (card.elementId
        ? '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-qw-bom="' +
          esc(card.elementId) +
          '" data-qw-bom-line="' +
          esc(card.lineId) +
          '" title="Engineering BOM">View BOM</button>'
        : "") +
      "</div>" +
      "</article>"
    );
  }

  function renderTotals(totals) {
    var t = totals || {};
    return (
      '<div class="qw-totals weos-ds-surface" id="qwTotals">' +
      '<div class="qw-totals__row"><span>Subtotal</span><strong>' +
      money(t.subtotal) +
      "</strong></div>" +
      '<div class="qw-totals__row"><span>Discount</span><strong>' +
      money(t.discount) +
      "</strong></div>" +
      '<div class="qw-totals__row"><span>Taxable</span><strong>' +
      money(t.taxable) +
      "</strong></div>" +
      '<div class="qw-totals__row"><span>GST</span><strong>' +
      money(t.gst) +
      "</strong></div>" +
      '<div class="qw-totals__row qw-totals__grand"><span>Grand</span><strong>' +
      money(t.grand) +
      "</strong></div>" +
      "</div>"
    );
  }

  function renderFilters(cards) {
    var floors = {};
    var locs = {};
    var pts = {};
    (cards || []).forEach(function (c) {
      if (c.floor) floors[c.floor] = true;
      if (c.location) locs[c.location] = true;
      if (c.productType) pts[c.productType] = true;
    });
    function opts(map, label) {
      return (
        '<option value="">' +
        label +
        "</option>" +
        Object.keys(map)
          .sort()
          .map(function (k) {
            return '<option value="' + esc(k) + '">' + esc(k) + "</option>";
          })
          .join("")
      );
    }
    return (
      '<div class="qw-filters" id="qwFilters">' +
      '<select id="qwFilterAll" aria-label="Filter all"><option value="">All</option></select>' +
      '<select id="qwFilterFloor" aria-label="Floor">' +
      opts(floors, "Floor") +
      "</select>" +
      '<select id="qwFilterLoc" aria-label="Location">' +
      opts(locs, "Location") +
      "</select>" +
      '<select id="qwFilterPt" aria-label="Product type">' +
      opts(pts, "Product Type") +
      "</select>" +
      "</div>"
    );
  }

  function renderWorkspace(payload) {
    var cards = (payload && payload.cards) || [];
    var grid =
      cards.length === 0
        ? '<p class="muted" id="qwEmpty">No designs on this quote yet. Use Add Design in Engineering, then Save.</p>'
        : '<div class="qw-card-grid" id="qwCardGrid">' +
          cards
            .map(function (c) {
              return renderCard(c);
            })
            .join("") +
          "</div>";
    return (
      '<div class="qw-review" data-batch="CANVAS-G">' +
      '<div class="qw-review__head">' +
      "<div><strong>Quote Review</strong>" +
      '<p class="muted" style="margin:.2rem 0 0;font-size:.8rem">Design cards manage all items — Engineering edits one. Canvas size stays independent of card count.</p></div>' +
      '<div class="qw-review__actions">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwFromTemplate">+ From Template</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwAddManual">+ Manual</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnQwAddProduct">+ Add Design</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwToEngineering">Engineering</button>' +
      "</div></div>" +
      (cards.length ? renderFilters(cards) : "") +
      grid +
      renderTotals(payload && payload.totals) +
      "</div>"
    );
  }

  function applyCardFilters() {
    var floor = (global.document.getElementById("qwFilterFloor") || {}).value || "";
    var loc = (global.document.getElementById("qwFilterLoc") || {}).value || "";
    var pt = (global.document.getElementById("qwFilterPt") || {}).value || "";
    var grid = global.document.getElementById("qwCardGrid");
    if (!grid) return;
    grid.querySelectorAll(".qw-card").forEach(function (card) {
      var ok = true;
      if (floor && card.getAttribute("data-floor") !== floor) ok = false;
      if (loc && card.getAttribute("data-location") !== loc) ok = false;
      if (pt && card.getAttribute("data-product-type") !== pt) ok = false;
      card.style.display = ok ? "" : "none";
    });
  }

  C.designCards = {
    renderCard: renderCard,
    renderTotals: renderTotals,
    renderWorkspace: renderWorkspace,
    applyCardFilters: applyCardFilters,
    money: money,
  };
})(typeof window !== "undefined" ? window : globalThis);
