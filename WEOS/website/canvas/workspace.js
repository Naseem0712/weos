/**
 * WEOS Canvas Batch D/D1 — Professional workspace chrome (tool rail + command bar + stage).
 * D1: primary cutover — TOOL RAIL | LARGE UC | PROPERTIES; legacy form wrapped.
 */
(function (global) {
  "use strict";

  var C = global.WEOSCanvas || (global.WEOSCanvas = {});

  var PRODUCT_CHOICES = [
    { type: "SLIDING_WINDOW", label: "Sliding Window", w: 1800, h: 1500, code: "W" },
    { type: "CASEMENT_WINDOW", label: "Casement Window", w: 1200, h: 1500, code: "C" },
    { type: "FIXED_WINDOW", label: "Fixed Window", w: 1200, h: 1200, code: "F" },
    { type: "FOLD_WINDOW", label: "Folding Window", w: 2400, h: 2100, code: "FD" },
    { type: "DOOR", label: "Door", w: 900, h: 2100, code: "D" },
    { type: "VENTILATOR", label: "Ventilator", w: 600, h: 450, code: "V" },
    { type: "SHOWER_PARTITION", label: "Shower Partition", w: 1200, h: 2000, code: "S" },
    { type: "LOUVER", label: "Louver", w: 1200, h: 1500, code: "L" },
    { type: "RAILING", label: "Railing", w: 2400, h: 900, code: "R" },
    { type: "PERGOLA", label: "Pergola", w: 4000, h: 3000, code: "P" },
    { type: "ACP", label: "ACP", w: 2400, h: 1800, code: "A" },
    { type: "GRILL", label: "Grill", w: 1200, h: 1200, code: "G" },
  ];

  function esc(s) {
    return String(s == null ? "" : s).replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  function toolBtn(id, label, reserved, titleOverride) {
    var title = titleOverride
      ? titleOverride
      : reserved
        ? label + " — INTENTIONALLY DISABLED until Canvas Batch E (Member + Grid + Cell)"
        : label;
    return (
      '<button type="button" class="uc-tool' +
      (reserved ? " is-reserved" : "") +
      '" data-uc-tool="' +
      id +
      '"' +
      (reserved ? " disabled aria-disabled=\"true\"" : "") +
      ' title="' +
      esc(title) +
      '"><span class="uc-tool__label">' +
      esc(label) +
      "</span>" +
      (reserved ? '<span class="uc-tool__soon">Batch E</span>' : "") +
      "</button>"
    );
  }

  function buildShellHtml() {
    return (
      '<div class="uc-workspace" data-batch="CANVAS-D1">' +
      '<div class="uc-command-bar weos-ds-toolbar" role="toolbar" aria-label="Canvas commands">' +
      '<div class="weos-ds-toolbar__group uc-cmd-identity">' +
      '<strong class="uc-cmd-title">Engineering Canvas</strong>' +
      '<span class="uc-cmd-design muted" data-uc="designLabel">Design</span>' +
      "</div>" +
      '<span class="weos-ds-toolbar__sep"></span>' +
      '<div class="weos-ds-toolbar__group">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="undo" disabled title="Undo">Undo</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="redo" disabled title="Redo">Redo</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="delete" disabled title="Delete unavailable">Delete</button>' +
      "</div>" +
      '<span class="weos-ds-toolbar__sep"></span>' +
      '<div class="weos-ds-toolbar__group">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="zoomOut" title="Zoom out">−</button>' +
      '<span class="uc-zoom-label muted" data-uc="zoomLabel">100%</span>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="zoomIn" title="Zoom in">+</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="fit" title="Fit">Fit</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="reset" title="Reset view">Reset</button>' +
      "</div>" +
      '<span class="weos-ds-toolbar__sep"></span>' +
      '<div class="weos-ds-toolbar__group">' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="gridToggle" title="Toggle grid">Grid</button>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm" data-uc="snapToggle" title="Toggle snap">Snap</button>' +
      '<label class="muted uc-floor-label" style="font-size:.72rem">Floor <select id="ucFloorSel" class="weos-ds-select"></select></label>' +
      '<label class="muted uc-floor-label" style="font-size:.72rem">Loc <select id="ucLocSel" class="weos-ds-select"></select></label>' +
      "</div>" +
      '<span class="weos-ds-toolbar__spacer"></span>' +
      '<div class="weos-ds-toolbar__group">' +
      '<span class="weos-ds-pill uc-save-pill" data-uc="saveStatus" data-kind="local">Local recovery</span>' +
      '<button type="button" class="weos-ds-btn weos-ds-btn--ghost weos-ds-btn--sm uc-props-toggle" data-uc="toggleProps" title="Toggle properties">Props</button>' +
      "</div>" +
      "</div>" +
      '<div class="uc-workspace-body">' +
      '<aside class="uc-tool-rail" aria-label="Canvas tools">' +
      toolBtn("select", "Select", false, "Select elements") +
      toolBtn("pan", "Pan", false, "Pan viewport") +
      toolBtn("measure", "Dim", false, "Show dimension overlay (display only — not measure-draw)") +
      '<div class="uc-tool-rail__sep"></div>' +
      toolBtn("member", "Member", true) +
      toolBtn("member_v", "V-Mem", true) +
      toolBtn("member_h", "H-Mem", true) +
      toolBtn("grid_split", "Cells", true) +
      "</aside>" +
      '<div class="uc-stage-wrap">' +
      '<div class="uc-viewport" tabindex="0" aria-label="Engineering viewport"></div>' +
      '<div class="uc-status-bar muted">' +
      '<span data-uc="cursorStatus">X — · Y — · Zoom 100%</span>' +
      '<span data-uc="selinfo">No selection</span>' +
      "</div>" +
      "</div>" +
      '<aside class="uc-props-rail" id="ucPropertyPanelHost" aria-label="Properties">' +
      '<div id="ucPropertyPanel" class="uc-property-panel"></div>' +
      "</aside>" +
      "</div>" +
      "</div>"
    );
  }

  function mountShell(rootEl) {
    if (!rootEl) throw new Error("workspace root required");
    rootEl.classList.add("uc-host", "uc-host--workspace");
    rootEl.innerHTML = buildShellHtml();
    return {
      workspace: rootEl.querySelector(".uc-workspace"),
      commandBar: rootEl.querySelector(".uc-command-bar"),
      toolRail: rootEl.querySelector(".uc-tool-rail"),
      viewport: rootEl.querySelector(".uc-viewport"),
      propsRail: rootEl.querySelector(".uc-props-rail"),
      propertyPanel: rootEl.querySelector("#ucPropertyPanel"),
      statusBar: rootEl.querySelector(".uc-status-bar"),
    };
  }

  function syncToolRail(toolRail, activeTool) {
    if (!toolRail) return;
    toolRail.querySelectorAll("[data-uc-tool]").forEach(function (btn) {
      var id = btn.getAttribute("data-uc-tool");
      var on = id === activeTool && !btn.disabled;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function syncSavePill(el, status) {
    if (!el) return;
    var labels = {
      local: "Local recovery",
      unsaved: "Unsaved",
      saving: "Saving…",
      saved: "Saved",
      error: "Save failed",
      server_draft: "Saved",
    };
    el.textContent = labels[status] || String(status || "Unsaved");
    el.dataset.kind = status || "unsaved";
  }

  function ensureProjectChrome() {
    var cart = global.document && global.document.getElementById("view-cart");
    if (!cart) return null;
    var existing = global.document.getElementById("ucProjectChrome");
    if (existing) return existing;
    var chrome = global.document.createElement("div");
    chrome.id = "ucProjectChrome";
    chrome.className = "uc-project-chrome";
    chrome.innerHTML =
      '<div class="uc-project-chrome__row">' +
      '<div class="uc-project-chrome__identity">' +
      '<strong id="ucWorkspaceTitle">Engineering Workspace</strong>' +
      '<span class="muted" id="ucSelectionTitle">No selection</span>' +
      "</div>" +
      '<div class="uc-project-chrome__setup" id="ucSetupCompact">' +
      '<span class="muted">Setup</span> <strong id="ucSetupText">—</strong>' +
      '<button type="button" class="btn ghost sm" id="btnUcEditSetup">Edit setup</button>' +
      "</div>" +
      '<div class="uc-project-chrome__actions">' +
      '<button type="button" class="btn sm" id="btnUcAddDesign">+ Add Design</button>' +
      '<button type="button" class="btn sm" id="btnUcAddToQuote" title="Save design to quote after server confirm">Add to Quote</button>' +
      '<button type="button" class="btn ghost sm" id="btnUcQuoteLines">Quote Review</button>' +
      "</div>" +
      "</div>";
    var split = cart.querySelector(".cart-split");
    if (split && split.parentNode) split.parentNode.insertBefore(chrome, split);
    else cart.insertBefore(chrome, cart.firstChild);
    return chrome;
  }

  function ensureAddDesignModal() {
    var existing = global.document.getElementById("ucAddDesignModal");
    if (existing) return existing;
    var modal = global.document.createElement("div");
    modal.id = "ucAddDesignModal";
    modal.className = "uc-add-design-modal hidden";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", "Add Design");
    var opts = PRODUCT_CHOICES.map(function (p) {
      return (
        '<button type="button" class="uc-add-design-opt" data-product-type="' +
        esc(p.type) +
        '" data-w="' +
        p.w +
        '" data-h="' +
        p.h +
        '" data-code="' +
        esc(p.code) +
        '"><strong>' +
        esc(p.label) +
        '</strong><span class="muted">' +
        p.w +
        "×" +
        p.h +
        " mm</span></button>"
      );
    }).join("");
    modal.innerHTML =
      '<div class="uc-add-design-modal__panel">' +
      '<div class="uc-add-design-modal__head">' +
      "<strong>Add Design</strong>" +
      '<button type="button" class="btn ghost sm" data-uc-add-close>Close</button>' +
      "</div>" +
      '<p class="muted" style="margin:.35rem 0 .75rem;font-size:.8rem">Choose a product. It opens on the Universal Canvas with the matching property panel — no separate designer popup.</p>' +
      '<div class="uc-add-design-grid">' +
      opts +
      "</div>" +
      "</div>";
    global.document.body.appendChild(modal);
    return modal;
  }

  function defaultSizeFor(productType) {
    for (var i = 0; i < PRODUCT_CHOICES.length; i++) {
      if (PRODUCT_CHOICES[i].type === productType) return PRODUCT_CHOICES[i];
    }
    return { type: productType, label: productType, w: 1200, h: 1200, code: "X" };
  }

  function openAddDesignModal() {
    var modal = ensureAddDesignModal();
    modal.classList.remove("hidden");
  }

  function closeAddDesignModal() {
    var modal = global.document.getElementById("ucAddDesignModal");
    if (modal) modal.classList.add("hidden");
  }

  function createDesignOnCanvas(productType, widthMm, heightMm, codePrefix) {
    var host = global.WEOS_UNIVERSAL_CANVAS_HOST;
    if (!host || !host.upsertLocalElement) return null;
    var meta = defaultSizeFor(productType);
    var w = Number(widthMm) || meta.w;
    var h = Number(heightMm) || meta.h;
    var prefix = codePrefix || meta.code || "X";
    var n = ((host.getViewModel && host.getViewModel().elements) || []).length + 1;
    var displayCode = prefix + "-" + String(n).padStart(2, "0");
    var id = "local-" + productType.toLowerCase() + "-" + Date.now().toString(36);
    var el = host.upsertLocalElement({
      elementId: id,
      displayCode: displayCode,
      productType: productType,
      widthMm: w,
      heightMm: h,
      // D3: deterministic world mm near origin; Fit uses widthMm×heightMm (not SVG viewBox).
      xMm: 0,
      yMm: 0,
    });
    // Immediate Fit to engineering mm (placeholder shares W×H with final artwork).
    host.selectElementById(id, { fit: true });
    try {
      if (C.designContext && C.designContext.getActive) {
        var dc = C.designContext.getActive({
          api: typeof global.api === "function" ? global.api : null,
        });
        dc.selectElement(
          Object.assign({}, el, {
            configPayload: { widthMm: w, heightMm: h },
          })
        );
        // Critical: fetch adapter SVG onto UC (placeholder until this resolves).
        // Property/SVG refresh must NOT re-Fit (no pendingPreviewFit here).
        if (typeof dc.refreshElementPreview === "function") {
          dc.refreshElementPreview(el, { widthMm: w, heightMm: h });
        }
      }
    } catch (e) {}
    closeAddDesignModal();
    return el;
  }

  function wireAddDesignUi() {
    ensureProjectChrome();
    ensureAddDesignModal();
    var addBtn = global.document.getElementById("btnUcAddDesign");
    if (addBtn && !addBtn._ucWired) {
      addBtn._ucWired = true;
      addBtn.onclick = function () {
        openAddDesignModal();
      };
    }
    var editSetup = global.document.getElementById("btnUcEditSetup");
    if (editSetup && !editSetup._ucWired) {
      editSetup._ucWired = true;
      editSetup.onclick = function () {
        if (typeof global.setView === "function") global.setView("setup");
      };
    }
    var quoteBtn = global.document.getElementById("btnUcQuoteLines");
    if (quoteBtn && !quoteBtn._ucWired) {
      quoteBtn._ucWired = true;
      quoteBtn.onclick = function () {
        if (C.quoteWorkspace && C.quoteWorkspace.showQuoteReview) {
          C.quoteWorkspace.showQuoteReview();
          return;
        }
        var cart = global.document.getElementById("view-cart");
        if (!cart) return;
        // D2: do not overlay quote list on canvas
        if (typeof global.setView === "function") global.setView("quote-review");
      };
    }
    var addToQuote = global.document.getElementById("btnUcAddToQuote");
    if (addToQuote && !addToQuote._ucWired) {
      addToQuote._ucWired = true;
      addToQuote.onclick = async function () {
        try {
          if (typeof global.requireCompanyLogin === "function" && !global.requireCompanyLogin()) return;
          var st = global.state || {};
          if (!st.projectId) {
            if (typeof global.toast === "function") {
              global.toast("Create Quote Setup first (New Quote), then Add to Quote");
            }
            if (typeof global.setView === "function") global.setView("setup");
            return;
          }
          // Prefer existing Add line path when a draft is configured; else save current selection snapshot
          if (typeof global.addDraftLineToCart === "function") {
            try {
              await global.addDraftLineToCart(null, { toastMsg: "Added to quote" });
            } catch (_) {
              // fall through to save
            }
          }
          if (typeof global.saveProject === "function") {
            await global.saveProject(false);
          }
          if (C.quoteWorkspace && C.quoteWorkspace.afterAddToQuote) {
            C.quoteWorkspace.afterAddToQuote();
          }
          if (typeof global.toast === "function") {
            global.toast("Saved to quote — open Quote Review for cards");
          }
        } catch (e) {
          if (typeof global.toast === "function") {
            global.toast((e && e.message) || String(e));
          }
        }
      };
    }
    var modal = global.document.getElementById("ucAddDesignModal");
    if (modal && !modal._ucWired) {
      modal._ucWired = true;
      modal.addEventListener("click", function (ev) {
        var t = ev.target;
        if (t === modal || (t && t.getAttribute && t.getAttribute("data-uc-add-close") != null)) {
          closeAddDesignModal();
          return;
        }
        var opt = t && t.closest ? t.closest("[data-product-type]") : null;
        if (!opt) return;
        createDesignOnCanvas(
          opt.getAttribute("data-product-type"),
          opt.getAttribute("data-w"),
          opt.getAttribute("data-h"),
          opt.getAttribute("data-code")
        );
      });
    }
    // Mirror setup summary text when present
    try {
      var src = global.document.getElementById("setupSummaryText");
      var dst = global.document.getElementById("ucSetupText");
      if (src && dst) dst.textContent = src.textContent || "—";
    } catch (e) {}
  }

  function applyPrimaryCutover(on) {
    var cart = global.document && global.document.getElementById("view-cart");
    if (!cart) return;
    if (on) {
      cart.classList.add("uc-mode", "uc-primary", "qw-engineering");
      cart.classList.remove("uc-show-quote");
      ensureProjectChrome();
      wireAddDesignUi();
      var tools = cart.querySelector(".cart-tools");
      if (tools) {
        tools.classList.add("uc-legacy-form");
        tools.setAttribute("data-uc-wrapped", "1");
      }
      var preview = cart.querySelector(".cart-preview");
      if (preview) preview.classList.add("uc-active");
      var navCart = global.document.querySelector('.navbtn[data-view="cart"]');
      if (navCart) navCart.textContent = "Design";
      var title = global.document.getElementById("title");
      if (title && !cart.classList.contains("hidden")) {
        title.textContent = "Engineering Workspace";
      }
      var subtitle = global.document.getElementById("subtitle");
      if (subtitle && !cart.classList.contains("hidden")) {
        subtitle.textContent = "Universal Canvas · Quote Review is separate";
      }
      var host = global.document.getElementById("universalCanvasHost");
      var ws = host && host.querySelector(".uc-workspace");
      if (ws) ws.classList.add("qw-compact-props");
      if (C.quoteWorkspace && C.quoteWorkspace.syncTopBar) {
        try {
          C.quoteWorkspace.syncTopBar();
        } catch (e) {}
      }
    } else {
      cart.classList.remove("uc-mode", "uc-primary", "uc-show-quote", "qw-engineering");
      var chrome = global.document.getElementById("ucProjectChrome");
      if (chrome) chrome.style.display = "none";
      var navCartOff = global.document.querySelector('.navbtn[data-view="cart"]');
      if (navCartOff) navCartOff.textContent = "Design";
    }
  }

  C.workspace = {
    buildShellHtml: buildShellHtml,
    mountShell: mountShell,
    syncToolRail: syncToolRail,
    syncSavePill: syncSavePill,
    applyPrimaryCutover: applyPrimaryCutover,
    openAddDesignModal: openAddDesignModal,
    closeAddDesignModal: closeAddDesignModal,
    createDesignOnCanvas: createDesignOnCanvas,
    PRODUCT_CHOICES: PRODUCT_CHOICES,
  };
})(typeof window !== "undefined" ? window : globalThis);
