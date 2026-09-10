/**
 * WEOS Canvas D2 — Quote Review design cards (authoritative saved data).
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

  function renderCard(card) {
    var warn =
      (card.warnings || []).length > 0
        ? '<ul class="qw-card__warn">' +
          (card.warnings || [])
            .slice(0, 4)
            .map(function (w) {
              return "<li>" + esc(w) + "</li>";
            })
            .join("") +
          "</ul>"
        : "";
    var preview = card.previewSvg
      ? '<div class="qw-card__preview" aria-hidden="true">' + card.previewSvg + "</div>"
      : '<div class="qw-card__preview qw-card__preview--empty muted">No saved preview</div>';
    return (
      '<article class="weos-ds-card qw-card" data-line-id="' +
      esc(card.lineId) +
      '" data-status="' +
      esc(card.status || "") +
      '">' +
      '<div class="qw-card__top">' +
      '<div><span class="weos-ds-card__k">ID</span><div class="qw-card__id">' +
      esc(card.lineId) +
      "</div></div>" +
      '<span class="qw-pill qw-pill--' +
      esc(card.status || "ready") +
      '">' +
      esc(card.status || "ready") +
      "</span>" +
      "</div>" +
      preview +
      "<strong class=\"qw-card__title\">" +
      esc(card.displayName || card.product || "Design") +
      "</strong>" +
      '<div class="qw-card__meta muted">' +
      esc(sizeLabel(card)) +
      " · Qty " +
      esc(card.qty) +
      (card.floor ? " · " + esc(card.floor) : "") +
      (card.location ? " · " + esc(card.location) : "") +
      "</div>" +
      '<div class="qw-card__specs muted">' +
      (card.series ? "Series " + esc(card.series) + " · " : "") +
      (card.glass ? esc(card.glass) + " · " : "") +
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

  function renderWorkspace(payload) {
    var cards = (payload && payload.cards) || [];
    var grid =
      cards.length === 0
        ? '<p class="muted" id="qwEmpty">No designs on this quote yet. Use Add Product in Engineering, then Add to Quote.</p>'
        : '<div class="qw-card-grid" id="qwCardGrid">' +
          cards
            .map(function (c) {
              return renderCard(c);
            })
            .join("") +
          "</div>";
    return (
      '<div class="qw-review" data-batch="CANVAS-D2">' +
      '<div class="qw-review__head">' +
      "<div><strong>Quote Review</strong>" +
      '<p class="muted" style="margin:.2rem 0 0;font-size:.8rem">Visual cards from saved quote data — not the live canvas form.</p></div>' +
      '<div class="qw-review__actions">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwAddManual">+ Manual product</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnQwAddProduct">+ Add Product</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwToEngineering">Engineering</button>' +
      "</div></div>" +
      grid +
      renderTotals(payload && payload.totals) +
      "</div>"
    );
  }

  C.designCards = {
    renderCard: renderCard,
    renderTotals: renderTotals,
    renderWorkspace: renderWorkspace,
    money: money,
  };
})(typeof window !== "undefined" ? window : globalThis);
