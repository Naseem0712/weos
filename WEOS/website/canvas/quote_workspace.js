/**
 * WEOS Canvas D2 — App entry + Engineering / Quote Review separation.
 * Compact top bar; no full quote list beside canvas; Quote Review is cards.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});
  var _lastWorkspace = null;
  var _mode = "engineering"; // engineering | quote_review

  function $(id) {
    return global.document.getElementById(id);
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  function money(n) {
    if (C.designCards && C.designCards.money) return C.designCards.money(n);
    var v = Number(n);
    if (!Number.isFinite(v)) return "₹ —";
    return "₹ " + Math.round(v);
  }

  function stateObj() {
    return global.state || {};
  }

  function ensureQuoteReviewView() {
    var existing = $("view-quote-review");
    if (existing) return existing;
    var main = global.document.querySelector(".main");
    if (!main) return null;
    var sec = global.document.createElement("section");
    sec.id = "view-quote-review";
    sec.className = "grid hidden";
    sec.setAttribute("data-batch", "CANVAS-D2");
    sec.innerHTML = '<div class="panel" id="qwReviewHost"><p class="muted">Open a quote to review designs.</p></div>';
    var cart = $("view-cart");
    if (cart && cart.parentNode) cart.parentNode.insertBefore(sec, cart.nextSibling);
    else main.appendChild(sec);
    return sec;
  }

  function ensureAppEntryView() {
    var existing = $("view-quote-home");
    if (existing) return existing;
    var main = global.document.querySelector(".main");
    if (!main) return null;
    var sec = global.document.createElement("section");
    sec.id = "view-quote-home";
    sec.className = "grid hidden";
    sec.setAttribute("data-batch", "CANVAS-D2");
    sec.innerHTML =
      '<div class="panel weos-ds-surface" id="qwHomePanel">' +
      "<strong>Quote / Design workspace</strong>" +
      '<p class="muted" style="margin:.4rem 0 .75rem;max-width:36rem">Engineering and Quote Review are separate. Create or restore a quote before adding products — nothing is created silently on open.</p>' +
      '<div class="row" style="gap:.5rem;flex-wrap:wrap">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnQwNewQuote">New Quote</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwRestoreDraft">Restore draft</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwOpenSetup">Quote Setup</button>' +
      "</div>" +
      '<div class="muted" id="qwHomeHint" style="margin-top:.75rem;font-size:.8rem"></div>' +
      "</div>";
    var dash = $("view-dashboard");
    if (dash && dash.parentNode) dash.parentNode.insertBefore(sec, dash.nextSibling);
    else main.appendChild(sec);
    return sec;
  }

  function ensureCompactTopBar() {
    var bar = $("qwTopBar");
    if (bar) return bar;
    var main = global.document.querySelector(".main");
    var top = main && main.querySelector(".top");
    if (!top || !top.parentNode) return null;
    bar = global.document.createElement("div");
    bar.id = "qwTopBar";
    bar.className = "qw-top-bar weos-ds-toolbar";
    bar.setAttribute("data-batch", "CANVAS-D2");
    bar.innerHTML =
      '<div class="qw-top-bar__identity">' +
      '<strong id="qwBarMode">Project Design</strong>' +
      '<span class="muted" id="qwBarQuote">Draft</span>' +
      '<span class="muted" id="qwBarCustomer">—</span>' +
      '<span class="muted" id="qwBarProject">—</span>' +
      "</div>" +
      '<div class="qw-top-bar__stats">' +
      '<span class="weos-ds-pill" id="qwBarItems">Items 0</span>' +
      '<span class="weos-ds-pill" id="qwBarAmount">₹ —</span>' +
      "</div>" +
      '<div class="qw-top-bar__actions">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwBarNew">New Quote</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwBarReview">Quote Review</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--sm" id="btnQwBarAdd">Add Design</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwBarSave">Save</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" id="btnQwBarPdf" disabled title="PDF when quote eligible">PDF</button>' +
      "</div>";
    top.parentNode.insertBefore(bar, top.nextSibling);
    return bar;
  }

  function syncTopBar(ctx) {
    ensureCompactTopBar();
    ctx = ctx || (_lastWorkspace && _lastWorkspace.context) || {};
    var st = stateObj();
    var qEl = $("qwBarQuote");
    var cEl = $("qwBarCustomer");
    var pEl = $("qwBarProject");
    var iEl = $("qwBarItems");
    var aEl = $("qwBarAmount");
    var modeEl = $("qwBarMode");
    if (modeEl) modeEl.textContent = _mode === "quote_review" ? "Quote Review" : "Project Design";
    if (qEl) {
      qEl.textContent = ctx.quotationId || st.projectId || "Draft";
    }
    if (cEl) cEl.textContent = ctx.customer || (typeof global.$ === "function" && global.$("cartCustomer") && global.$("cartCustomer").value) || "—";
    if (pEl) pEl.textContent = ctx.name || (typeof global.$ === "function" && global.$("cartName") && global.$("cartName").value) || "—";
    var count = ctx.itemCount != null ? ctx.itemCount : (st.lines || []).length;
    var amount = ctx.amount != null ? ctx.amount : null;
    if (iEl) iEl.textContent = "Items " + count;
    if (aEl) aEl.textContent = money(amount);
    var pdfBtn = $("btnQwBarPdf");
    if (pdfBtn) pdfBtn.disabled = !(st.projectId && count > 0);
  }

  function setEngineeringChrome() {
    var cart = $("view-cart");
    if (!cart) return;
    cart.classList.add("uc-mode", "uc-primary", "qw-engineering");
    cart.classList.remove("uc-show-quote");
    // Never park a quote list beside the canvas in D2
    var quoteBtn = $("btnUcQuoteLines");
    if (quoteBtn) {
      quoteBtn.textContent = "Quote Review";
      quoteBtn.title = "Open Quote Review (separate from canvas)";
    }
    var chrome = $("ucProjectChrome");
    if (chrome) {
      var title = $("ucWorkspaceTitle");
      if (title) title.textContent = "Engineering Workspace";
    }
    // Compact props
    var host = $("universalCanvasHost");
    var ws = host && host.querySelector(".uc-workspace");
    if (ws) ws.classList.add("qw-compact-props");
  }

  async function refreshWorkspaceFromServer() {
    var st = stateObj();
    if (!st.projectId || typeof global.api !== "function") {
      _lastWorkspace = null;
      syncTopBar({ itemCount: (st.lines || []).length, amount: null });
      return null;
    }
    try {
      var payload = await global.api("/api/projects/" + encodeURIComponent(st.projectId) + "/quote-workspace");
      _lastWorkspace = payload;
      syncTopBar(payload.context || {});
      return payload;
    } catch (e) {
      syncTopBar({ itemCount: (st.lines || []).length });
      return null;
    }
  }

  async function showQuoteReview() {
    _mode = "quote_review";
    ensureQuoteReviewView();
    ensureCompactTopBar();
    // Reveal Quote Review section without re-entering setView (avoids recursion)
    try {
      stateObj().view = "quote-review";
      document.querySelectorAll(".navbtn").forEach(function (b) {
        b.classList.toggle("active", b.dataset.view === "cart");
      });
      ["dashboard", "setup", "master", "projects", "cart", "library", "product", "admin", "customers", "company", "scan", "learning", "formulas", "templates", "engines", "quote-home", "quote-review"].forEach(function (id) {
        var el = $("view-" + id);
        if (!el) return;
        el.classList.toggle("hidden", id !== "quote-review");
      });
      var t = $("title");
      var s = $("subtitle");
      if (t) t.textContent = "Quote Review";
      if (s) s.textContent = "Design cards · totals · duplicate · PDF";
    } catch (_) {}
    var host = $("qwReviewHost");
    if (host) host.innerHTML = '<p class="muted">Loading quote…</p>';
    var payload = await refreshWorkspaceFromServer();
    if (!host) return;
    if (!payload) {
      host.innerHTML =
        '<p class="muted">No active quote. Use <strong>New Quote</strong> → Quote Setup, then add designs.</p>';
      syncTopBar({});
      return;
    }
    if (C.designCards && C.designCards.renderWorkspace) {
      host.innerHTML = C.designCards.renderWorkspace(payload);
    }
    wireQuoteReviewActions(payload);
    syncTopBar(payload.context || {});
  }

  function findLineIndex(lineId) {
    var lines = stateObj().lines || [];
    for (var i = 0; i < lines.length; i++) {
      if (String((lines[i] || {}).lineId || "") === String(lineId)) return i;
    }
    return -1;
  }

  /**
   * D4: keep Quote Review card in sync with the same item ID after geometry/config edits.
   * Updates dims / preview / summary locally; amount only when calculable on the line.
   */
  function syncCardFromElement(element, previewSvg) {
    element = element || {};
    var st = stateObj();
    var lines = st.lines || [];
    var eid = element.elementId || element.id;
    var code = element.displayCode || element.designSerial;
    var idx = -1;
    if (typeof st.selectedLine === "number" && st.selectedLine >= 0) {
      idx = st.selectedLine;
    }
    if (idx < 0 && eid) {
      for (var i = 0; i < lines.length; i++) {
        var ln = lines[i] || {};
        if (
          String(ln.elementId || "") === String(eid) ||
          String(ln.designElementId || "") === String(eid) ||
          String(ln.lineId || "") === String(eid)
        ) {
          idx = i;
          break;
        }
      }
    }
    if (idx < 0 && code) {
      for (var j = 0; j < lines.length; j++) {
        var ln2 = lines[j] || {};
        if (String(ln2.designSerial || ln2.lineId || "") === String(code)) {
          idx = j;
          break;
        }
      }
    }
    if (idx < 0 || !lines[idx]) return false;
    var line = lines[idx];
    var w = element.widthMm != null ? Number(element.widthMm) : Number(line.width);
    var h = element.heightMm != null ? Number(element.heightMm) : Number(line.height);
    if (isFinite(w) && w > 0) line.width = w;
    if (isFinite(h) && h > 0) line.height = h;
    if (previewSvg) {
      line.previewSvg = previewSvg;
      if (!line.quotation) line.quotation = {};
      line.quotation.previewSvg = previewSvg;
    }
    if (element.productType) line.productType = element.productType;
    // Recalc amount when rate + area known
    try {
      var rate = Number(line.sellingRate || line.rate || (line.quotation && line.quotation.sellingPerUnit));
      var unit = String(line.saleUnit || (line.quotation && line.quotation.saleUnit) || "sqft").toLowerCase();
      var qty = Number(line.qty || line.quantity || 1) || 1;
      if (isFinite(rate) && rate > 0 && isFinite(w) && isFinite(h) && w > 0 && h > 0) {
        var area = unit === "sqft" ? (w * h) / 92903.04 : unit === "sqm" ? (w * h) / 1e6 : 1;
        if (unit === "nos" || unit === "each") area = 1;
        line.amount = Math.round(rate * area * qty);
      }
    } catch (_) {}
    lines[idx] = line;
    st.lines = lines;

    // Live DOM patch on Quote Review if open
    try {
      var card = global.document && global.document.querySelector('.qw-card[data-line-id="' + String(line.lineId || "").replace(/"/g, "") + '"]');
      if (card) {
        var meta = card.querySelector(".qw-card__meta");
        if (meta) {
          var size =
            (isFinite(w) ? Math.round(w) : "—") + "×" + (isFinite(h) ? Math.round(h) : "—") + " mm";
          meta.textContent =
            size +
            " · Qty " +
            (line.qty || line.quantity || 1) +
            (line.floor ? " · " + line.floor : "") +
            (line.location ? " · " + line.location : "");
        }
        if (previewSvg) {
          var prev = card.querySelector(".qw-card__preview");
          if (prev) {
            prev.classList.remove("qw-card__preview--empty", "muted");
            prev.innerHTML = previewSvg;
          }
        }
        if (line.amount != null) {
          var amt = card.querySelector(".qw-card__amount");
          if (amt && C.designCards && C.designCards.money) {
            amt.textContent = C.designCards.money(line.amount);
          }
        }
      }
    } catch (_) {}
    syncTopBar({
      itemCount: lines.length,
      amount: lines.reduce(function (s, L) {
        return s + (Number(L.amount) || 0);
      }, 0),
    });
    return true;
  }

  function wireQuoteReviewActions(payload) {
    var host = $("qwReviewHost");
    if (!host || host._qwWired === payload.projectId) {
      // still rebind buttons each render
    }
    var add = $("btnQwAddProduct");
    if (add) {
      add.onclick = function () {
        goEngineering();
        if (C.workspace && C.workspace.openAddDesignModal) C.workspace.openAddDesignModal();
      };
    }
    var man = $("btnQwAddManual");
    if (man) {
      man.onclick = function () {
        goEngineering();
        if (typeof global.setView === "function") global.setView("cart");
        // Reveal legacy form briefly for manual commercial path only
        var cart = $("view-cart");
        if (cart) {
          cart.classList.add("qw-manual-path");
          var tools = cart.querySelector(".cart-tools");
          if (tools) {
            tools.classList.add("qw-manual-panel");
            tools.style.display = "block";
          }
        }
        if (typeof global.toast === "function") {
          global.toast("Manual product: fill the form, then Add to Quote");
        }
      };
    }
    var eng = $("btnQwToEngineering");
    if (eng) eng.onclick = function () {
      goEngineering();
    };
    host.querySelectorAll("[data-qw-edit]").forEach(function (btn) {
      btn.onclick = function () {
        var lid = btn.getAttribute("data-qw-edit");
        editDesign(lid);
      };
    });
    host.querySelectorAll("[data-qw-dup]").forEach(function (btn) {
      btn.onclick = function () {
        var lid = btn.getAttribute("data-qw-dup");
        openDupFor(lid, payload);
      };
    });
  }

  function openDupFor(lineId, payload) {
    var card = ((payload && payload.cards) || []).find(function (c) {
      return String(c.lineId) === String(lineId);
    });
    var st = stateObj();
    if (C.designDuplicate && C.designDuplicate.open) {
      C.designDuplicate.open({
        lineId: lineId,
        projectId: st.projectId || (payload && payload.projectId),
        displayName: card && card.displayName,
        widthMm: card && card.widthMm,
        heightMm: card && card.heightMm,
        qty: card && card.qty,
        floor: card && card.floor,
        location: card && card.location,
        mark: card && card.mark,
        sellingRate: card && card.sellingRate,
      });
    }
  }

  async function editDesign(lineId) {
    var idx = findLineIndex(lineId);
    goEngineering();
    if (idx < 0) {
      // Reload from server then try again
      try {
        if (stateObj().projectId && typeof global.openProject === "function") {
          await global.openProject(stateObj().projectId);
          idx = findLineIndex(lineId);
        }
      } catch (_) {}
    }
    if (idx >= 0 && typeof global.renderCart === "function") {
      stateObj().selectedLine = idx;
      // Trigger select path used by cart table
      try {
        var row = document.querySelector('#cartBody [data-sel="' + idx + '"]');
        if (row) row.click();
      } catch (_) {}
    }
    if (typeof global.toast === "function") {
      global.toast("Editing design " + lineId + " (same ID)");
    }
  }

  function goEngineering() {
    _mode = "engineering";
    var cart = $("view-cart");
    if (cart) {
      cart.classList.remove("qw-manual-path", "uc-show-quote");
      var tools = cart.querySelector(".cart-tools");
      if (tools) {
        tools.style.display = "";
        tools.classList.remove("qw-manual-panel");
      }
    }
    if (typeof global.setView === "function") global.setView("cart");
    setEngineeringChrome();
    syncTopBar(_lastWorkspace && _lastWorkspace.context);
  }

  function goNewQuote() {
    if (typeof global.resetSetupFormForNew === "function") global.resetSetupFormForNew();
    else {
      stateObj().projectId = null;
      stateObj().lines = [];
    }
    _lastWorkspace = null;
    if (typeof global.setView === "function") global.setView("setup");
    syncTopBar({});
    if (typeof global.toast === "function") {
      global.toast("Quote Setup — save customer/project, then Add Design");
    }
  }

  async function restoreDraft(projectId) {
    if (!projectId) return;
    if (typeof global.openProject === "function") {
      await global.openProject(projectId);
    }
    await showQuoteReview();
  }

  async function runAppEntry(opts) {
    opts = opts || {};
    ensureAppEntryView();
    ensureCompactTopBar();
    ensureQuoteReviewView();
    wireTopBarOnce();
    wireHomeOnce();

    var loggedIn = typeof global.isCompanyLoggedIn === "function" ? global.isCompanyLoggedIn() : !!(stateObj().companyGst);
    if (!loggedIn) {
      if (typeof global.setView === "function") global.setView("company");
      return { action: "login" };
    }

    var plan = null;
    try {
      if (typeof global.api === "function") {
        plan = await global.api("/api/quote-workspace/app-entry");
      }
    } catch (_) {}

    var hint = $("qwHomeHint");
    var st = stateObj();

    // Prefer local session project if already known (refresh persistence)
    if (st.projectId && !opts.forceHome) {
      try {
        await global.openProject(st.projectId);
        await showQuoteReview();
        return { action: "restore_session", projectId: st.projectId };
      } catch (_) {}
    }

    if (plan && plan.action === "restore_draft" && plan.projectId && !opts.forceNew) {
      if (hint) {
        hint.textContent =
          "Draft " +
          (plan.quotationId || plan.projectId) +
          (plan.customer ? " · " + plan.customer : "") +
          " — Restore or start New Quote.";
      }
      if (typeof global.setView === "function") global.setView("quote-home");
      // auto-restore for refresh continuity when preferRestore
      if (opts.autoRestore !== false) {
        await restoreDraft(plan.projectId);
        return plan;
      }
      return plan;
    }

    if (typeof global.setView === "function") global.setView("quote-home");
    if (hint) {
      hint.textContent = (plan && plan.message) || "Start with New Quote → Quote Setup, then Add Design.";
    }
    return plan || { action: "new_quote_setup" };
  }

  function wireHomeOnce() {
    var home = ensureAppEntryView();
    if (!home || home._qwWired) return;
    home._qwWired = true;
    var n = $("btnQwNewQuote");
    if (n) n.onclick = goNewQuote;
    var r = $("btnQwRestoreDraft");
    if (r) {
      r.onclick = async function () {
        try {
          var plan = await global.api("/api/quote-workspace/app-entry");
          if (plan && plan.projectId) await restoreDraft(plan.projectId);
          else if (typeof global.toast === "function") global.toast("No draft found");
        } catch (e) {
          if (typeof global.toast === "function") global.toast((e && e.message) || String(e));
        }
      };
    }
    var s = $("btnQwOpenSetup");
    if (s) {
      s.onclick = function () {
        if (typeof global.setView === "function") global.setView("setup");
      };
    }
  }

  function wireTopBarOnce() {
    var bar = ensureCompactTopBar();
    if (!bar || bar._qwWired) return;
    bar._qwWired = true;
    var neu = $("btnQwBarNew");
    if (neu) neu.onclick = goNewQuote;
    var rev = $("btnQwBarReview");
    if (rev) rev.onclick = function () {
      showQuoteReview();
    };
    var add = $("btnQwBarAdd");
    if (add) {
      add.onclick = function () {
        var st = stateObj();
        if (!st.projectId) {
          if (typeof global.toast === "function") {
            global.toast("Create Quote Setup first (New Quote), then Add Design");
          }
          goNewQuote();
          return;
        }
        goEngineering();
        if (C.workspace && C.workspace.openAddDesignModal) C.workspace.openAddDesignModal();
      };
    }
    var save = $("btnQwBarSave");
    if (save) {
      save.onclick = async function () {
        try {
          if (typeof global.saveProject === "function") await global.saveProject(false);
          await refreshWorkspaceFromServer();
        } catch (e) {
          if (typeof global.toast === "function") global.toast((e && e.message) || String(e));
        }
      };
    }
    var pdf = $("btnQwBarPdf");
    if (pdf) {
      pdf.onclick = function () {
        if (typeof global.generateProjectPdf === "function") global.generateProjectPdf();
        else if (typeof global.openProjectPdf === "function") global.openProjectPdf("customer");
      };
    }
  }

  function patchNavLabels() {
    var navCart = global.document.querySelector('.navbtn[data-view="cart"]');
    if (navCart) navCart.textContent = "Design";
    var setupBtn = $("btnSetupToCart");
    if (setupBtn) setupBtn.textContent = "Continue to Engineering";
    // Neutralize Window Cart copy in setup if present
    try {
      global.document.querySelectorAll("#view-setup p, #view-setup .muted, #view-setup button").forEach(function (el) {
        if (el.childElementCount === 0 && /Window Cart/i.test(el.textContent || "")) {
          el.textContent = (el.textContent || "").replace(/Window Cart/gi, "Engineering");
        }
      });
    } catch (_) {}
  }

  function onDuplicated(res) {
    if (res && res.project && Array.isArray(res.project.lines) && typeof global.hydrateCartLines === "function") {
      stateObj().lines = global.hydrateCartLines(res.project.lines);
    } else if (res && res.workspace) {
      _lastWorkspace = res.workspace;
    }
    if (typeof global.renderCart === "function") global.renderCart();
    if (typeof global.persistCartSession === "function") global.persistCartSession();
    if (typeof global.toast === "function") {
      global.toast("Duplicated " + (res.createdCount || 0) + " design(s) with new IDs");
    }
    showQuoteReview();
  }

  function afterAddToQuote() {
    refreshWorkspaceFromServer().then(function () {
      syncTopBar(_lastWorkspace && _lastWorkspace.context);
    });
  }

  function installSetViewHook() {
    // setView in index.html already routes quote-review / quote-home — no wrap needed.
    ensureQuoteReviewView();
    ensureAppEntryView();
    ensureCompactTopBar();
  }

  function boot() {
    installSetViewHook();
    patchNavLabels();
    ensureCompactTopBar();
    ensureAppEntryView();
    ensureQuoteReviewView();
    wireTopBarOnce();
    wireHomeOnce();
    // Redirect Quote lines button → Quote Review
    setTimeout(function () {
      var quoteBtn = $("btnUcQuoteLines");
      if (quoteBtn && !quoteBtn._qwD2) {
        quoteBtn._qwD2 = true;
        quoteBtn.onclick = function () {
          showQuoteReview();
        };
      }
      var editSetup = $("btnUcEditSetup");
      if (editSetup && !editSetup._qwD2) {
        editSetup._qwD2 = true;
        editSetup.onclick = function () {
          if (typeof global.setView === "function") global.setView("setup");
        };
      }
    }, 0);
  }

  C.quoteWorkspace = {
    boot: boot,
    runAppEntry: runAppEntry,
    showQuoteReview: showQuoteReview,
    goEngineering: goEngineering,
    goNewQuote: goNewQuote,
    refreshWorkspaceFromServer: refreshWorkspaceFromServer,
    syncTopBar: syncTopBar,
    setEngineeringChrome: setEngineeringChrome,
    syncCardFromElement: syncCardFromElement,
    onDuplicated: onDuplicated,
    afterAddToQuote: afterAddToQuote,
    getLastWorkspace: function () {
      return _lastWorkspace;
    },
  };

  if (global.document && global.document.readyState === "loading") {
    global.document.addEventListener("DOMContentLoaded", boot);
  } else {
    try {
      boot();
    } catch (_) {}
  }
})(typeof window !== "undefined" ? window : globalThis);
