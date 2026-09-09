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

### Combined regression gate (after B8)

Re-run after B9 with contextual properties smoke.

---

## Remaining batches (from user plan / target doc)

Contextual Property Panel — **NEXT ELIGIBLE**. Production deployment — **NOT PERFORMED**.

## Checkpoint (current session)

- **Starting HEAD:** `2020822640ef85c63f7b76db04bf2c569aee3703`
- **Ending HEAD:** (B8 commit)
- **Branch:** weos-v2-foundation
- Unrelated dirty left untouched: product stubs, weos.db, company/profile.json, glass catalogue seed, WEOS/customers/, _tmp_*, railway tomls, blueprint/gap docs, etc.
- Production deployment: **NOT PERFORMED**
- Next eligible batch: **Contextual Property Panel (B9)**
- Hard stop after B8 alone: no — B9 authorized in same session after B8 PASS+push
