# WEOS V2 Implementation Progress

**Branch:** `weos-v2-foundation`  
**Authority:** `_audit/WEOS_TARGET_ARCHITECTURE_AND_GAP_PLAN.md`  
**Started:** 2026-09-09  
**Starting HEAD:** `32b0c9505c4a982b0898304f61a768a108071385` (`main`)  
**Production deployment:** NOT PERFORMED

---

## Batch log

### BATCH 0 — Baseline & Safety

| Field | Value |
|---|---|
| **ID** | B0 |
| **Goal** | Git safety, smoke baseline, progress tracker, dead-code inventory |
| **Files** | `_audit/WEOS_IMPLEMENTATION_PROGRESS.md`, `_audit/WEOS_DEAD_CODE_REGISTER.md` |
| **Schema / migration** | None |
| **Tests** | See smoke matrix below |
| **Issues** | Pre-existing FAIL on several ledger/login smokes (recorded, not treated as regressions) |
| **Commit** | `32012d6` — `docs(audit): WEOS v2 batch 0 progress and dead code register` |
| **Push** | Pushed to `origin/weos-v2-foundation` |
| **Rollback** | Delete/revert these two audit docs only |

#### Dirty tree at start (preserved, not committed)

- Modified: `WEOS/company/profile.json`, product stub JSON, `WEOS/weos.db`, `knowledge_base/libraries/glass_catalogue/_seeded.json`
- Untracked junk/tmp: `_tmp_*`, `diff_files.txt`, `file_local.txt`, `file_remote.txt`, `railway_*.toml`, `remote_tree.txt`, `WEOS/customers/`
- Untracked audit: `_audit/` (this batch owns progress + dead-code docs only)

#### Smoke matrix (Batch 0 baseline)

| Area | Smoke / method | Result | Notes |
|---|---|---|---|
| Login / company isolation | `_smoke_company_login.py` | **FAIL (pre-existing)** | PIN/session OK; fails at scanner approve: missing customer mobile for last-6 verify |
| Company workspace / GST | `_smoke_gst_workspace.py` | **FAIL (pre-existing)** | billed/balance mismatch vs expected latest-version basis |
| Quote identity | `_smoke_quote_identity_flow.py` | **PASS** | |
| Quotation totals | `_smoke_quote_totals.py` | **PASS** | |
| PDF (cart quote) | `_smoke_quote_pdf_cart.py` | **PASS** | |
| QR / scanner privacy | `_smoke_public_scan_security.py` | **PASS** | |
| Railing (normal) | `_smoke_normal_railing.py` | **PASS** | |
| Stair railing | `_smoke_stair_railing.py` | **PASS** | |
| Casement | `_smoke_casement_mullion.py` | **PASS** | |
| Windows / sliding | `_smoke_sliding_track_opening.py` | **PASS** | |
| Project import | `_smoke_project_import.py` | **FAIL (pre-existing)** | import OK; fails `ledger advances 0` after commit |
| Master ledger | `_smoke_master_ledger.py` | **PASS** | |
| Company ledger | `_smoke_company_ledger.py` | **FAIL (pre-existing)** | billed/balance inflated vs expected |
| Quote lifecycle | `_smoke_quote_lifecycle.py` | **FAIL (pre-existing)** | draft billed into turnover |
| Money / payment specs | `_smoke_money_specs.py` | **PASS** | |
| Project save/load | covered via identity + PDF + ledger smokes | **PASS (partial)** | no dedicated isolated smoke |
| Customer profile API ownership | dedicated test added in B1 | **NOT RUN in B0** | ungated at baseline (gap) |
| Staircase (beyond stair railing) | — | **NOT RUN** | no separate smoke found beyond `_smoke_stair_railing.py` |

---

### BATCH 1 — Security Hotfix

| Field | Value |
|---|---|
| **ID** | B1 |
| **Goal** | Server-side company ownership on project/customer sensitive routes |
| **Files** | `WEOS/factory/company_workspace.py`, `WEOS/api/server.py`, `WEOS/website/index.html` (session on PDF links), `WEOS/_smoke_tenant_ownership.py` |
| **Schema / migration** | None |
| **Tests** | New `_smoke_tenant_ownership.py` + re-run B0 key smokes that must not regress |
| **Issues** | PDF/xlsx browser tabs need `?session=` (header-only would break print links); query session accepted by `require_company_gst` |
| **Commit** | `f16beec` — `fix(security): enforce tenant ownership on project and customer routes` |
| **Push** | Pushed to `origin/weos-v2-foundation` |
| **Rollback** | Revert B1 commit; UI session query is additive |

#### B1 verification

| Test | Result |
|---|---|
| `_smoke_tenant_ownership.py` | **PASS** — unauth 401; cross-tenant 404; owner R/W + PDF/ledger OK; companyGst spoof ignored |
| `_smoke_quote_identity_flow.py` | **PASS** (regression) |
| `_smoke_quote_totals.py` | **PASS** (regression) |
| `_smoke_public_scan_security.py` | **PASS** (regression) |
| `_smoke_quote_pdf_cart.py` | **PASS** (regression) |
| `_smoke_master_ledger.py` | **PASS** (regression) |
| `_smoke_money_specs.py` | **PASS** (regression) |

---

### BATCH 2 — Save / Durability Honesty

| Field | Value |
|---|---|
| **ID** | B2 |
| **Goal** | SQL authoritative project save; UI never claims “saved” for browser-only draft; fail closed on SQL write failure |
| **Files** | `WEOS/factory/project_store.py`, `WEOS/api/server.py`, `WEOS/website/index.html`, `WEOS/_smoke_persistence_durability.py` |
| **Schema / migration** | None |
| **Tests** | `_smoke_persistence_durability.py` **PASS**; `_smoke_tenant_ownership.py` **PASS** (re-verified this session) |
| **Issues** | None — B2 committed as `488d917`, pushed to `origin/weos-v2-foundation`, smokes PASS |
| **Commit** | `488d917` — `fix(persistence): make server SQL save authoritative` |
| **Push** | Pushed to `origin/weos-v2-foundation` |
| **Rollback** | Revert `488d917` if the durability gate later fails in a clean shell session |

#### B2 implementation

- `save_project`: SQL write first; `DurableSaveError` if `_db_put_project` fails; FS is cache after success only; response flags `persisted`/`durable`/`saveKind=server_draft`
- API create/update/calculate: map `DurableSaveError` → HTTP 503
- UI: `#savePill`; `scheduleSave` → local recovery only (never “Saved”); `saveProject`/`ensureProject` require durable confirmation; toasts say “Server draft saved”
- New smoke: `_smoke_persistence_durability.py` (save/reload/reopen + mocked SQL failure must raise and not leave FS-only success)

#### Required verify commands (PowerShell)

```
cd "d:\Downloads\window cad model"
$env:PYTHONPATH="."
$env:PYTHONIOENCODING="utf-8"
python WEOS/_smoke_persistence_durability.py
python WEOS/_smoke_tenant_ownership.py
python WEOS/_smoke_quote_identity_flow.py
python WEOS/_smoke_quote_pdf_cart.py
git add WEOS/factory/project_store.py WEOS/api/server.py WEOS/website/index.html WEOS/_smoke_persistence_durability.py _audit/WEOS_IMPLEMENTATION_PROGRESS.md
git commit -m "fix(persistence): make server SQL save authoritative"
git push origin weos-v2-foundation
```

---

### BATCH 3 — Canonical Customer Identity

| Field | Value |
|---|---|
| **ID** | B3 |
| **Goal** | Company-scoped immutable customer_id (CUS-…); mobile/GST/name as discovery identities only; no silent merges |
| **Files committed** | WEOS/db/models.py, WEOS/factory/canonical_customer.py, WEOS/_smoke_canonical_customer.py, WEOS/factory/customer_store.py |
| **Schema / migration** | Additive tables canonical_customers + customer_identities (+ CanonicalProject model for FK spine) via create_all; migrate_legacy_customer_profiles() |
| **Tests** | _smoke_canonical_customer.py PASS; _smoke_tenant_ownership.py PASS; durability PASS before commit |
| **Migration counts (from smoke)** | MIGRATE_CUSTOMER_COUNTS {before: 2, created: 0, linked: 1, conflicts: 0, rejected: 0, skipped: 1, after: 1, manualReview: 0} — zeroSilentLoss: True |
| **Issues** | None for B3 |
| **Commit** | 888bfd2 — feat(customer): add canonical company-scoped customer identity |
| **Push** | Pushed with B4 to origin/weos-v2-foundation |
| **Rollback** | Revert 888bfd2 (before B4) or both B3+B4 commits |

#### B3 notes

- Stamp customerId via ensure_customer_from_profile **before** FS/DB profile write
- Cross-company same mobile allowed; identity conflicts refuse silent merge
- Did **not** commit WEOS/customers/, weos.db, product stubs, or unrelated dirty files

---

### BATCH 4 — Canonical Project Identity

| Field | Value |
|---|---|
| **ID** | B4 |
| **Goal** | Company→Customer→Project spine; preserve PRJ-… ids; name match scoped within customer; refuse silent customer reassignment |
| **Files committed** | WEOS/factory/canonical_project.py, WEOS/_smoke_canonical_project.py, WEOS/factory/project_store.py, WEOS/_smoke_persistence_durability.py |
| **Schema / migration** | Additive canonical_projects; migrate_legacy_projects() |
| **Tests** | _smoke_canonical_project.py PASS; durability PASS; tenant ownership PASS |
| **Migration counts (from smoke)** | MIGRATE_PROJECT_COUNTS {before: 1, created: 0, linked: 1, unmatched: 0, ambiguous: 0, rejected: 0, after: 1, manualReview: 0, zeroSilentLoss: True} |
| **Issues** | None for B4 |
| **Commit** | a69c1cd — feat(project): canonicalize project ownership and identity |
| **Push** | Pushed to origin/weos-v2-foundation |
| **Rollback** | Revert a69c1cd (keeps B3) or revert B3+B4 |

#### B4 notes

- link_project_document stamps customerId / canonicalProjectId before authoritative SQL write
- Durability smoke updated to match fail-closed _db_put_project path (no db_ready mock)

---

### Combined regression gate (after B3+B4)

All PASS (exit 0): durability, canonical customer, canonical project, tenant ownership, quote identity, quote totals, public scan, quote PDF cart, money specs, normal railing, stair railing, sliding track opening, casement mullion.

### Pre-existing smoke failures (classification)

| Smoke | Symptom | Classification | Root / status | Blocks B3/B4? |
|---|---|---|---|---|
| `_smoke_company_login.py` scanner last-6 | `apply_scanner_status(... mobile=...)` raises “Customer Mobile number is not saved for verification” | **DATA/FIXTURE ISSUE** (+ mild **TEST EXPECTATION STALE**) | Smoke creates project with `customer="Pin Cust"` but never sets `customerMobile` on the doc; verifier reads expected mobile from project | **DOES NOT BLOCK** |
| `_smoke_gst_workspace.py` billed/balance | expects billed 125000 (latest) got sum of versions / multi-quote | **ARCHITECTURAL ISSUE** / **EXISTING APPLICATION BUG** | Workspace totals not “latest_per_quotation_number”; drafts/extra versions inflate billed | **DOES NOT BLOCK** B3/B4; **BLOCKS** later ledger/budget batches |
| `_smoke_gst_hub_persist.py` | billed/balance/taxable/grand mismatch + missing customer/project restore | **EXISTING APPLICATION BUG** | GST hub ledger aggregation / persist restore against wrong basis totals | **DOES NOT BLOCK** |
| `_smoke_project_import.py` ledger advances | import commit OK but `ledger advances 0` | **EXISTING APPLICATION BUG** | Advances committed on import path not visible to ledger query for that customer/GST | **DOES NOT BLOCK** B3/B4; **BLOCKS** payment-ledger migration |
| `_smoke_company_ledger.py` billed/balance | billed 177000 vs expected 150000 | **ARCHITECTURAL ISSUE** / **EXISTING APPLICATION BUG** | Same totals-basis drift as GST workspace (drafts / multi-version inclusion) | **DOES NOT BLOCK** B3/B4; **BLOCKS** financial SoT cutover |
| `_smoke_quote_lifecycle.py` draft billed | draft included in billed (240000 vs 80000) | **EXISTING APPLICATION BUG** | Draft status not excluded from turnover/billed aggregates | **DOES NOT BLOCK** B3/B4; **BLOCKS** budget/approval accounting |

---

### BATCH 5 — Floor / Location / DesignDocument foundation

| Field | Value |
|---|---|
| **ID** | B5 |
| **Goal** | Project→Floor→Location→DesignDocument (+ GeometryRevision); legacy locationName → Unassigned system floor |
| **Files committed** | `WEOS/db/models.py`, `WEOS/factory/design_hierarchy.py`, `WEOS/api/design_routes.py`, `WEOS/api/server.py` (router include), `WEOS/_smoke_design_hierarchy.py`, `_audit/WEOS_IMPLEMENTATION_PROGRESS.md` |
| **Schema / migration** | Additive tables `floors`, `locations`, `design_documents`, `geometry_revisions` via create_all; `migrate_legacy_locations()` |
| **Legacy rule** | Free-text `locationName` maps to system floor **Unassigned** (`code=UNASSIGNED`). Never invent Ground Floor without evidence. |
| **Tests** | `_smoke_design_hierarchy.py` cases A–H **PASS**; B5 regression suite **PASS** |
| **Migration counts (from smoke)** | projectsInspected: 1, floorsCreated: 0 (Unassigned already from G), locationsCreated: 1, legacyLocationNamesLinked: 2, unassignedItems: 1, conflicts: 0, rejected: 0, manualReview: 0, zeroSilentLoss: True |
| **Issues** | None for B5 |
| **Commit** | `e3690dd` — `feat(design): add floor location and design document foundation` |
| **Push** | Pushed to `origin/weos-v2-foundation` |
| **Rollback** | Revert `e3690dd` |

#### B5 notes

- Thin APIs in `design_routes.py`; domain logic in `design_hierarchy.py`
- GeometryRevision immutable once created; DesignDocument draft payload remains mutable
- Company session → project ownership for Floor/Location/DesignDocument (isolation in smoke F)
- Did **not** commit weos.db, product stubs, customers/, _tmp_*, or unrelated dirty files

---

### BATCH 6 — Assembly / Element / Connection domain

| Field | Value |
|---|---|
| **ID** | B6 |
| **Goal** | DesignDocument → Assembly → Element + Connection; cart-line adapter; scene read model (no Canvas UI) |
| **Files committed** | `WEOS/db/models.py`, `WEOS/factory/design_scene.py`, `WEOS/api/design_routes.py`, `WEOS/_smoke_design_scene.py`, `_audit/WEOS_IMPLEMENTATION_PROGRESS.md` |
| **Schema / migration** | Additive `assemblies`, `design_elements`, `connections`; `migrate_cart_lines_to_scene()` / `adapt_cart_line_to_assembly_element()` |
| **Connection types** | adjacent_independent, frame_to_frame, coupler, shared_mullion, shared_transom, top_bottom_join, corner, custom |
| **Tests** | `_smoke_design_scene.py` cases 1–7 **PASS**; combined B5+B6 gate **PASS** |
| **Migration counts (from smoke)** | legacyLinesInspected: 1, assembliesMapped: 1, elementsMapped: 1, unmapped: 0, conflicts: 0, rejected: 0, manualReview: 0, zeroSilentLoss: True |
| **Issues** | None for B6 — drawing engines / BOM / pricing untouched |
| **Commit** | `12c585b` — `feat(design): add assembly element and connection domain` |
| **Push** | Pushed to `origin/weos-v2-foundation` |
| **Rollback** | Revert `12c585b` (keeps B5) |

#### B6 notes

- Single product = Assembly + one Element; mixed products + unequal W/H/X/Y supported
- Element geometry independent of series (series in `config_payload` only)
- Connections explicit only — touching geometry does not imply Connection
- Cart adapter does not mutate dims/product/location/qty/money/preview
- Universal Canvas UI **NOT STARTED** (hard stop after B6)

### Combined regression gate (after B5+B6)

All PASS (exit 0): durability, canonical customer, canonical project, tenant ownership, design hierarchy, design scene, quote identity, quote totals, public scan, PDF cart, money specs, normal railing, stair railing, sliding, casement.

---

### BATCH 7 — Universal Engineering Canvas Host

| Field | Value |
|---|---|
| **ID** | B7 |
| **Goal** | One UniversalCanvas host: viewport/zoom/pan/selection/labels/scene load/adapters; keep `#livePreview` via `WEOS_UNIVERSAL_CANVAS` flag |
| **Files committed** | `WEOS/factory/universal_canvas.py`, `WEOS/website/canvas/{universal_canvas,viewport,scene_renderer,selection,adapters}.js`, `WEOS/api/design_routes.py`, `WEOS/website/index.html`, `WEOS/_smoke_universal_canvas.py`, `_audit/WEOS_IMPLEMENTATION_PROGRESS.md` |
| **Schema / migration** | None (uses B5/B6 DesignDocument/Element SQL); pose via `PATCH /api/elements/{id}/pose` |
| **Feature flag** | `WEOS_UNIVERSAL_CANVAS` default **OFF**; `/api/flags`; URL `?universalCanvas=1` |
| **Tests** | `_smoke_universal_canvas.py` A–H **PASS**; B7 regression suite **PASS** (16/16) |
| **Issues** | Element drag-to-move deferred (`ELEMENT_DRAG_ENABLED=False`); pose save via API only |
| **Commit** | (see git) — `feat(canvas): introduce universal engineering canvas host` |
| **Push** | `origin/weos-v2-foundation` |
| **Rollback** | Flag OFF restores `#livePreview`; revert B7 commit |

#### B7 notes

- ONE host — no WindowCanvas/RailingCanvas split
- Zoom/pan display-only; engineering W/H never mutated by viewport
- Adapters: preview-SVG for known product types; placeholder fallback (ID + type + W×H)
- Floor/Location selectors use canonical IDs; labels from scene displayCode
- Product forms / engines / BOM / cost / GST / PDF untouched
- Hard stop: no product plugin migration; old preview/forms not deleted

### Combined regression gate (after B7)

All PASS (exit 0): durability, canonical customer, canonical project, tenant ownership, design hierarchy, design scene, universal canvas, quote identity, quote totals, public scan, PDF cart, money specs, normal railing, stair railing, sliding, casement.

---

### BATCH 8 — Product Plugin Adapters

| Field | Value |
|---|---|
| **ID** | B8 |
| **Goal** | Connect product engines to ONE Universal Canvas via registry adapters (no WindowCanvas/RailingCanvas) |
| **Files committed** | `WEOS/factory/product_adapters.py`, `WEOS/factory/universal_canvas.py`, `WEOS/factory/design_scene.py` (`update_element`/`update_assembly`), `WEOS/api/design_routes.py`, `WEOS/website/canvas/adapters.js`, `WEOS/_smoke_product_adapters.py`, `_audit/WEOS_IMPLEMENTATION_PROGRESS.md` |
| **Schema / migration** | None |
| **Tests** | `_smoke_product_adapters.py` **PASS**; `_smoke_universal_canvas.py` **PASS** |
| **Issues** | None — engines reused; unknown → placeholder fallback |
| **Commit** | (see git) — `feat(canvas): connect product engines through universal adapters` |
| **Push** | `origin/weos-v2-foundation` |
| **Rollback** | Revert B8 commit; B7 canvas host remains |

#### B8 notes

- Adapter contract: supports / loadConfiguration / renderPreview / validate / getPropertySchema / updateConfiguration / calculate
- Window family: Sliding/Fixed/Casement/Door/Fold via existing `generate_job` + SVG (no geometry_engine rewrite)
- Railing/Ventilator/Shower via existing engines; louvers/pergola/grill/surface thin schematics
- Exact product types preserved — WINDOW collapse refused
- Mixed A-01 Sliding+Fixed+Ventilator on same Universal Canvas
- Hard stop: Contextual Property Panel is B9
- **PARITY PENDING: Pergola** — B8 shipped with pergola as thin schematic only; tools/schema insufficient for first-class PERGOLA (posts/beams/rafters/louvers/side zones/roof/deck). Completion queued as **Batch 8.5 / 9.5** (not a separate canvas). **(Cleared in Batch 8.5/9.5 — see below.)**

### Combined regression gate (after B8)

Re-run after B9 with contextual properties smoke.

---

### BATCH 9 — Contextual Property Panel

| Field | Value |
|---|---|
| **ID** | B9 |
| **Goal** | ONE contextual property panel synced to selection IDs; wrap/hide legacy tool stacks when UC ON |
| **Files committed** | `WEOS/factory/contextual_properties.py`, `WEOS/api/design_routes.py`, `WEOS/website/canvas/property_panel.js`, `WEOS/website/index.html`, `WEOS/_smoke_contextual_properties.py`, `_audit/WEOS_IMPLEMENTATION_PROGRESS.md`, `_audit/WEOS_DEAD_CODE_REGISTER.md` |
| **Schema / migration** | None |
| **Tests** | `_smoke_contextual_properties.py` **PASS**; combined gate 18/18 **PASS** |
| **Issues** | Visual interactive cart login not fully exercised; static panel + API verified |
| **Commit** | (see git) — `feat(ui): add contextual product property panel` |
| **Push** | `origin/weos-v2-foundation` |
| **Rollback** | Flag OFF restores legacy tools; revert B9 commit |

#### B9 notes

- Selection by elementId / assemblyId / connectionId (not DOM/row index)
- Window / Railing / Ventilator / Assembly / Connection schemas — no cross-product pollution
- When `WEOS_UNIVERSAL_CANVAS` ON: `#railTools` / `#showerTools` / `#ventTools` / `#windowCartTools` hidden (PARITY PENDING — not deleted)
- Property updates: Panel → geometry/config split → SQL save → preview; fail closed
- **PARITY PENDING: Pergola** — B9 property schemas do not cover first-class Pergola groups; unfinished B8/B9 product surface (see Batch 8.5 / 9.5). **(Cleared in Batch 8.5/9.5.)**
- Hard stop after B9: next *architecture* eligible was Engineering Master Data / BOM Foundation; **product gap** Pergola completion is inserted in the UX/PDF queue below (not a new architecture)

### Combined regression gate (after B8+B9)

All PASS (exit 0): durability, canonical customer, canonical project, tenant ownership, design hierarchy, design scene, universal canvas, product adapters, contextual properties, quote identity, quote totals, public scan, PDF cart, money specs, normal railing, stair railing, sliding, casement.

---

### BATCH 8.5 / 9.5 — Pergola Product Adapter + Property Panel + Print/PDF

| Field | Value |
|---|---|
| **ID** | B8.5 / B9.5 |
| **Goal** | First-class **PERGOLA** on Universal Canvas: adapter registry + contextual property panel + quote/print design summary + PDF preflight — **no** PergolaCanvas / separate viewport |
| **Status** | **DONE** |
| **Scope** | Product-specific B8/B9 completion — not a separate canvas architecture |
| **Files committed** | `WEOS/factory/pergola_model.py`, `WEOS/factory/product_adapters.py`, `WEOS/factory/special_schematics.py`, `WEOS/factory/project_engine.py`, `WEOS/factory/window_specs.py`, `WEOS/factory/pdf_preflight.py`, `WEOS/factory/contextual_properties.py`, `WEOS/factory/design_scene.py`, `WEOS/products/pergola_stub/*`, `WEOS/_smoke_pergola_adapter.py`, `WEOS/_smoke_product_adapters.py`, `WEOS/_smoke_contextual_properties.py`, `_audit/WEOS_IMPLEMENTATION_PROGRESS.md`, `_audit/WEOS_DEAD_CODE_REGISTER.md` |
| **Geometry** | W / D / H / qty; posts, beams, rafters, louvers; Front / Left / Right / Back side zones; roof; optional deck |
| **UI** | Property panel groups: Geometry, Structure, Louvers, Roof, Side Treatments, Floor/Deck, Finish, Summary |
| **PDF** | Design summary in quote/print specs; preflight requires Pergola summary fields and refuses silent omit |
| **Tests** | `_smoke_pergola_adapter.py` + extended product adapters / contextual properties |
| **Schema / migration** | Additive config only (`configPayload` / `options.pergola`) — no giant domain rewrite |
| **Commit / Push** | See commits below; pushed to `origin/weos-v2-foundation` |
| **Rollback** | Revert B8.5/B9.5 commits only; leave B7–B9 host + other adapters intact |

#### B8.5 / B9.5 notes

- Root cause: B8/B9 registered Pergola as thin schematic only (`schematic_pergola`) with colour/notes schema — insufficient for sides/roof/deck/structure and print summary
- `PergolaAdapter` (`adapter_id=pergola`) replaces thin path; reuses `special_schematics.pergola_svg`
- ONE Universal Canvas only — no `PergolaCanvas`
- Geometry independent of materials; Front/Left/Right/Back are distinct zones
- Save/reload via SQL design_scene + property panel APIs (not DOM-only)
- **PARITY PENDING: Pergola** cleared for adapter/panel/print surface; full structural engineering / BOM still out of scope
- Hard stop: do **not** start PDF Viewer Redesign (Batch B) or Engineering Master Data/BOM in this batch

#### Queue order (strict)

1. ~~UX/PDF **Batch A — PDF reliability**~~ **DONE**
2. ~~**Batch 8.5 / 9.5 — Pergola**~~ **DONE**
3. ~~UX/PDF **Batch B — PDF Viewer Redesign**~~ **DONE** (@ `a8e8894`)
4. ~~**UX Batch C — WEOS Design System foundation**~~ **DONE**
5. ~~**Canvas D0 — Product Context / Stale State / Single Canvas Parity**~~ **DONE**
6. **Next eligible:** **Canvas Batch D** — Professional Universal Canvas Workspace (**QUEUED**)
7. Then **Canvas Batch E** — Member + Grid + Cell Engine (**QUEUED**)
8. Then **Canvas Batch F** — Cell Product Assignment (**QUEUED**)
9. Then **Canvas Batch G** — Design Management (**QUEUED**)
10. Architecture track (Engineering Master Data / BOM Foundation, etc.) remains **separate** — attach **after** C–G foundations are stable
11. Production deployment — **NOT AUTHORIZED / NOT PERFORMED**

**HARD STOP (this plan-update turn):** Do **not** implement UX C or Canvas D/E/F/G. Do **not** rewrite Batch B. Docs only.

---

### BATCH A — PDF Reliability (UX/PDF)

| Field | Value |
|---|---|
| **ID** | UX-PDF-A |
| **Goal** | Guarantee complete quotation content + drawing validation; no silent omit; no demo term substitutes; preflight before Download/Print |
| **Files committed** | `WEOS/factory/pdf_preflight.py`, `WEOS/factory/pdf_engine.py`, `WEOS/factory/marqt_pdf.py`, `WEOS/factory/elevation_cache.py`, `WEOS/factory/line_kind.py`, `WEOS/api/server.py`, `WEOS/website/index.html`, `WEOS/_smoke_pdf_reliability.py`, `_audit/WEOS_IMPLEMENTATION_PROGRESS.md` |
| **Schema / migration** | None |
| **Architecture** | Live cart payload today; future `QuoteSnapshot` feeds same preflight + `render_marqt_pdf` (`pdfFailClosed` / `pdfExpectedLineIds`) — no second competing PDF architecture |
| **Tests** | `_smoke_pdf_reliability.py` **PASS**; critical regression gate **PASS** (see below) |
| **Issues** | Known finance/login smoke failures unchanged; smoke needles align with bathroom-vent PDF titles |
| **Commit** | `fix(pdf): guarantee complete quotation content and drawing validation` |
| **Push** | `origin/weos-v2-foundation` |
| **Rollback** | Revert Batch A commit; Universal Canvas left alone |

#### Batch A notes

- Preflight: items, drawings, manual fields, specs, terms source, totals → READY or Error with missing IDs
- Strict cart coerce on customer PDF (unresolved IDs → 422); merge preserves durable `preview.svg`
- Fail-closed customer path: no minimal/demo PDF degrade; empty terms ≠ demo inject
- Manual products: drawing optional; name/qty/unit/rate required
- Universal Canvas / Engineering Master Data / BOM / QuoteFamily **not started**
- Smoke assertion: bathroom vent lines match PDF formatter title (`Bathroom ventilator`), not cart `displayName` alone

#### Batch A gate results (2026-09-10)

| Smoke | Result |
|---|---|
| `_smoke_pdf_reliability.py` | **PASS** |
| `_smoke_persistence_durability.py` | **PASS** |
| `_smoke_canonical_customer.py` | **PASS** |
| `_smoke_canonical_project.py` | **PASS** |
| `_smoke_tenant_ownership.py` | **PASS** |
| `_smoke_design_hierarchy.py` | **PASS** |
| `_smoke_design_scene.py` | **PASS** |
| `_smoke_universal_canvas.py` | **PASS** |
| `_smoke_product_adapters.py` | **PASS** |
| `_smoke_contextual_properties.py` | **PASS** |
| `_smoke_quote_identity_flow.py` | **PASS** |
| `_smoke_quote_totals.py` | **PASS** |
| `_smoke_public_scan_security.py` | **PASS** |
| `_smoke_quote_pdf_cart.py` | **PASS** |
| `_smoke_money_specs.py` | **PASS** |
| `_smoke_normal_railing.py` | **PASS** |
| `_smoke_stair_railing.py` | **PASS** |
| `_smoke_sliding_track_opening.py` | **PASS** |
| `_smoke_casement_mullion.py` | **PASS** |

---

### BATCH B — PDF Viewer Redesign (UX/PDF)

| Field | Value |
|---|---|
| **ID** | UX-PDF-B |
| **Goal** | Professional quotation PDF preview UX: Preparing / Validating / Ready / Error; maximize document space; wire Batch A preflight errors into clear missing-item UI |
| **Files committed** | `WEOS/website/index.html`, `WEOS/_smoke_pdf_viewer_ux.py`, `_audit/WEOS_IMPLEMENTATION_PROGRESS.md` |
| **Schema / migration** | None |
| **Architecture** | Viewer-only; same live-cart → preflight → render path as Batch A; remains Snapshot-ready (no second PDF architecture) |
| **Tests** | `_smoke_pdf_viewer_ux.py` **PASS**; `_smoke_pdf_reliability.py` **PASS**; critical regression gate **PASS** (21/21) |
| **Issues** | Native PDF toolbar suppression best-effort via `#toolbar=0` (browser-dependent) |
| **Commit** | `feat(pdf): redesign quotation preview and download experience` |
| **Push** | `origin/weos-v2-foundation` |
| **Rollback** | Revert Batch B commit(s); Batch A fail-closed left intact |

#### Batch B notes

- Loading: centered “Preparing Quotation PDF” + compact progress; no empty grey iframe before bytes exist; quote/project identity in header
- Ready: PDF dominates viewport; compact bar Back | Quote number | Print | Download
- Error: Batch A `errors` / `missingIds` listed with Retry + Back to Quote — never blank incomplete “valid” PDF
- Fake multi-tab progress pills / machine theatre removed → phase indicator only
- Engineering calculations / quote amounts / item identity untouched
- Universal Canvas / Engineering Master Data / BOM / QuoteFamily **not started**

#### Batch B gate results (2026-09-10)

| Smoke | Result |
|---|---|
| `_smoke_pdf_viewer_ux.py` | **PASS** |
| `_smoke_pdf_reliability.py` | **PASS** (fail-closed intact) |
| Critical regression gate (21) | **PASS** |

Gate smokes: durability, canonical customer/project, tenant ownership, design hierarchy/scene, universal canvas, product adapters, contextual properties, pergola, pdf reliability, pdf viewer ux, quote identity, quote totals, public scan, quote PDF cart, money specs, normal railing, stair railing, sliding, casement — all **PASS**.

#### Batch B ending HEAD (verified)

| Field | Value |
|---|---|
| **Local + remote tip** | `a8e889411dd75f0621388684b0b75abffae63de0` (`a8e8894`) on `weos-v2-foundation` / `origin/weos-v2-foundation` |
| **Status** | COMPLETE / TESTED / PUSHED — do **not** rewrite Batch B |

---

### UX BATCH C — WEOS Design System foundation (**DONE**)

| Field | Value |
|---|---|
| **ID** | UX-C |
| **Status** | **DONE** — tested locally; pushed to origin (Production NOT PERFORMED) |
| **Goal** | Shared WEOS UI primitives: tokens, buttons, inputs, dialogs, toolbar, cards, property sections, layout primitives |
| **Files** | `WEOS/website/design-system/tokens.css`, `components.css`, `weos-ds.js`; progressive link/script in `WEOS/website/index.html`; `WEOS/_smoke_design_system.py`; `_audit/WEOS_IMPLEMENTATION_PROGRESS.md` |
| **Schema / migration** | None |
| **Depends on** | Batch B complete (`a8e8894`); tip before Batch C finish: `011b624` |
| **Tests** | `_smoke_design_system.py` **PASS**; critical regression gate **PASS** (21/21 — see below) |
| **Issues** | Progressive integration only — not a full SPA redesign; Canvas D not started |
| **Commit** | `feat(ui): introduce WEOS application design system` (+ optional docs stamp) |
| **Push** | `origin/weos-v2-foundation` |
| **Rollback** | Revert Batch C commit(s); remove design-system link/script from index if needed |
| **Hard stop** | Do **not** start Canvas D/E/F/G inside this batch; no Production deploy |
| **Authority** | Target plan **ACD.11** (Advanced Canvas Design Workflow) |

#### Batch C gate results (2026-09-10)

| Smoke | Result |
|---|---|
| `_smoke_design_system.py` | **PASS** |
| `_smoke_persistence_durability.py` | **PASS** |
| `_smoke_canonical_customer.py` | **PASS** |
| `_smoke_canonical_project.py` | **PASS** |
| `_smoke_tenant_ownership.py` | **PASS** |
| `_smoke_design_hierarchy.py` | **PASS** |
| `_smoke_design_scene.py` | **PASS** |
| `_smoke_universal_canvas.py` | **PASS** |
| `_smoke_product_adapters.py` | **PASS** |
| `_smoke_contextual_properties.py` | **PASS** |
| `_smoke_pergola_adapter.py` | **PASS** |
| `_smoke_pdf_reliability.py` | **PASS** |
| `_smoke_pdf_viewer_ux.py` | **PASS** |
| `_smoke_quote_identity_flow.py` | **PASS** |
| `_smoke_quote_totals.py` | **PASS** |
| `_smoke_public_scan_security.py` | **PASS** |
| `_smoke_quote_pdf_cart.py` | **PASS** |
| `_smoke_money_specs.py` | **PASS** |
| `_smoke_normal_railing.py` | **PASS** |
| `_smoke_stair_railing.py` | **PASS** |
| `_smoke_sliding_track_opening.py` | **PASS** |
| `_smoke_casement_mullion.py` | **PASS** |

#### Queue order (strict)

1. ~~UX/PDF **Batch A — PDF reliability**~~ **DONE**
2. ~~**Batch 8.5 / 9.5 — Pergola**~~ **DONE**
3. ~~UX/PDF **Batch B — PDF Viewer Redesign**~~ **DONE** (`a8e8894`)
4. ~~**UX Batch C — WEOS Design System foundation**~~ **DONE**
5. ~~**Canvas D0 — Product Context / Stale State / Single Canvas Parity**~~ **DONE**
6. **Next eligible:** **Canvas Batch D** — Professional Universal Canvas Workspace (**QUEUED**)
7. Then **Canvas Batch E** — Member + Grid + Cell Engine (**QUEUED**)
8. Then **Canvas Batch F** — Cell Product Assignment (**QUEUED**)
9. Then **Canvas Batch G** — Design Management (**QUEUED**)
10. Architecture track (Engineering Master Data / BOM Foundation, etc.) remains **separate**
11. Production deployment — **NOT AUTHORIZED / NOT PERFORMED**

---

### CANVAS D0 — Product Context / Stale State / Single Canvas Parity (**DONE**)

| Field | Value |
|---|---|
| **ID** | CANVAS-D0 |
| **Status** | **DONE** |
| **Goal** | ONE ActiveDesignContext; product_type → registry → schema → renderer → toolset; no WINDOW fallthrough; no stale model/tools across switches; UC ON = one viewport (legacy designers routed into UC) |
| **Files committed** | `WEOS/factory/design_context.py`, `WEOS/factory/product_adapters.py`, `WEOS/factory/contextual_properties.py`, `WEOS/api/design_routes.py`, `WEOS/website/canvas/design_context.js`, `WEOS/website/canvas/{property_panel,universal_canvas}.js`, `WEOS/website/index.html`, `WEOS/_smoke_product_context_switching.py`, `_audit/WEOS_IMPLEMENTATION_PROGRESS.md` |
| **Schema / migration** | None (context + specialized schemas only) |
| **APIs** | `GET /api/design-context`, `POST /api/design-context/switch` |
| **Tests** | `_smoke_product_context_switching.py` A–N **PASS**; design system / UC / adapters / contextual / pergola / design scene+hierarchy / PDF reliability+viewer / critical gate **PASS** |
| **Issues** | Live browser visual with `?universalCanvas=1` deferred if no safe local server in session |
| **Commit** | `fix(canvas): isolate product context and prevent stale designer state` |
| **Push** | `origin/weos-v2-foundation` |
| **Rollback** | Revert D0 commit(s); B7–B9 / Pergola / PDF / Design System foundations retained |
| **Hard stop** | **Do NOT auto-start Canvas Batch D** |

#### D0 notes

- Root causes: dual ownership (legacy `applyProductWorld` + UC panel); WINDOW/`sliding` fallthrough; shared preview/mode flags; MutationObserver mirroring wrong SVG; no atomic context clear on catalogue switch
- ActiveDesignContext owns selectedProductType, elementId, assemblyId, adapterId, propertySchema, toolset, renderer, renderRevision
- Casement ≠ Sliding schema fields; unsupported → guidance message (not Window tools)
- UC ON: legacy tool stacks stay wrapped; second `#universalCanvasHost` refused; specialty calc skipped under UC
- Element-scoped `configScope` (`element:{id}` / `draft:{type}`) — no shared `currentWindowConfig`
- Async: `renderRevision` + AbortController discard stale renders; clear transient `#livePreview` only

#### Queue order (strict)

1. ~~UX/PDF **Batch A — PDF reliability**~~ **DONE**
2. ~~**Batch 8.5 / 9.5 — Pergola**~~ **DONE**
3. ~~UX/PDF **Batch B — PDF Viewer Redesign**~~ **DONE**
4. ~~**UX Batch C — WEOS Design System foundation**~~ **DONE**
5. ~~**Canvas D0 — Product Context parity**~~ **DONE**
6. **Next eligible:** **Canvas Batch D** — Professional Universal Canvas Workspace (**QUEUED**)
7. Then **Canvas Batch E** — Member + Grid + Cell Engine (**QUEUED**)
8. Then **Canvas Batch F** — Cell Product Assignment (**QUEUED**)
9. Then **Canvas Batch G** — Design Management (**QUEUED**)
10. Architecture track (Engineering Master Data / BOM Foundation, etc.) remains **separate**
11. Production deployment — **NOT AUTHORIZED / NOT PERFORMED**

---

### CANVAS BATCH D — Professional Universal Canvas Workspace (**QUEUED**)

| Field | Value |
|---|---|
| **ID** | CANVAS-D |
| **Status** | **QUEUED** after Canvas D0 |
| **Goal** | Left tool rail, command toolbar, grid, selection improvements, snap foundation, dimensions, undo/redo foundation — on **ONE** Universal Canvas |
| **Hard stop** | No FrameMember / Cell engine (Batch E); no second canvas |
| **Authority** | ACD.2–ACD.3, ACD.8, ACD.11 |

---

### CANVAS BATCH E — Member + Grid + Cell Engine (**QUEUED**)

| Field | Value |
|---|---|
| **ID** | CANVAS-E |
| **Status** | **QUEUED** after Canvas D |
| **Goal** | FrameMember domain; vertical/horizontal drawing; cell subdivision; stable cell IDs; SQL persistence; tests |
| **Hard stop** | No cell product-assignment UX (Batch F); members = domain data not decorative SVG |
| **Authority** | ACD.4–ACD.5, ACD.12 |

---

### CANVAS BATCH F — Cell Product Assignment (**QUEUED**)

| Field | Value |
|---|---|
| **ID** | CANVAS-F |
| **Status** | **QUEUED** after Canvas E |
| **Goal** | Fixed / Sliding / Casement / Ventilator / Door / panel; structure vs infill/behavior; contextual schemas; mixed assembly |
| **Hard stop** | No Design Management polish (Batch G); keep Geometry ≠ behavior ≠ series ≠ config |
| **Authority** | ACD.6–ACD.7, ACD.12 |

---

### CANVAS BATCH G — Design Management (**QUEUED**)

| Field | Value |
|---|---|
| **ID** | CANVAS-G |
| **Status** | **QUEUED** after Canvas F |
| **Goal** | Add Design; Duplicate Design with explicit scale rules (PROPORTIONAL / FIXED DIMENSION / USER CHOICE — no silent guess); Project Design cards; floor/location workflow |
| **Hard stop** | Deep Window Master / profile BOM waits until C–G stable; Duplicate = new ID, never mutate original |
| **Authority** | ACD.9–ACD.11, ACD.12 |

---

## Remaining batches (from user plan / target doc)

**Immediate queue:** ~~Batch A~~ **DONE** → ~~Pergola 8.5/9.5~~ **DONE** → ~~Batch B PDF Viewer~~ **DONE** → ~~UX Batch C~~ **DONE** → ~~Canvas D0~~ **DONE** → **Next: Canvas D** → E → F → G.  
Engineering Master Data / BOM Foundation remains on the architecture track **after** C–G foundations are stable.  
**HARD STOP:** Canvas D/E/F/G **not started** (D0 complete). Production deployment — **NOT PERFORMED / NOT AUTHORIZED**.

---

## Session checkpoint (Canvas D0)

- **Branch:** `weos-v2-foundation`
- **Starting HEAD:** `8c023706c6eaf02134ac160460cb85101fdd1b0a`
- **Ending HEAD:** (see D0 commit after push)
- **Next eligible implementation:** **Canvas Batch D** — Professional Universal Canvas Workspace
- **Do not start:** Canvas D automatically in this turn; Production deploy
- **Preserved:** B5–B9, Pergola 8.5/9.5, PDF A/B, UX C foundations; unrelated dirty files not committed

## Checkpoint (current session — Batch C COMPLETE)

- **Starting HEAD:** `011b624d7e04235a49187a7b0d21463bc2461215` on `weos-v2-foundation`
- **Ending HEAD:** 632b12b3f7969897dfa9a285df4469d6d3e2565c (632b12b) on weos-v2-foundation / origin/weos-v2-foundation
- **Batch C:** **COMPLETE** — design system smoke PASS; critical regression 21/21 PASS; selective commit + push
- **Canvas D–G:** not started (HARD STOP after C)
- Production deployment: **NOT PERFORMED**
- **Next eligible implementation:** **Canvas Batch D** — Professional Universal Canvas Workspace
- Unrelated dirty tree left untouched
- Recovery script `_tmp_batch_c_finish.ps1` left untracked (not committed)

