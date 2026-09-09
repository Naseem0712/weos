# WEOS Dead Code Register

**Purpose:** Classify modules before deletion. Do **not** delete `UNKNOWN`. Only delete `CONFIRMED UNUSED` after checks A–H.  
**Date:** 2026-09-09  
**Checks A–H:** A import graph · B routes · C frontend refs · D startup · E engine plugins · F tests/smokes · G data/migrations · H deployment/entrypoints

| Status | Meaning |
|---|---|
| ACTIVE | Live product path |
| ACTIVE LEGACY | Live but scheduled for replace/migrate |
| COMPATIBILITY REQUIRED | Needed for old clients / data |
| TEST-ONLY | Smokes / fixtures |
| MIGRATION-ONLY | Import/migrate helpers |
| CONFIRMED UNUSED | Proven unused by A–H — eligible for separate delete commit |
| UNKNOWN | Not fully proven — **keep** |

---

## Initial inventory (Batch 0)

| Path / area | Classification | Evidence / notes | Delete? |
|---|---|---|---|
| `WEOS/api/server.py` | ACTIVE | Primary FastAPI app | No |
| `WEOS/api/main.py` | ACTIVE | App entry | No |
| `WEOS/api/calculate.py` | ACTIVE | Calc API surface | No |
| `WEOS/factory/pipeline.py` + geometry/svg/bom/quotation engines | ACTIVE | Window/door engineering plugins | No |
| `WEOS/factory/railing_*.py` | ACTIVE | Railing plugin | No |
| `WEOS/factory/ventilator_engine.py` / `shower_engine.py` | ACTIVE | Product plugins | No |
| `WEOS/factory/panel_fills.py` / `special_schematics.py` | ACTIVE | Louvers/pergola/ACP-style thin schematics | No |
| Pergola first-class adapter / property schema / print summary | **ACTIVE** (Batch 8.5/9.5) | `pergola_model.py` + `PergolaAdapter`; thin `schematic_pergola` path removed from registry. Full structural engineering / BOM still out of scope — not a delete candidate for `special_schematics.pergola_svg` | No |
| `WEOS/factory/project_store.py` | ACTIVE LEGACY | FS+SQL mirror SoT today; migrate later | No |
| `WEOS/factory/customer_store.py` | ACTIVE LEGACY | Name-slug profiles; migrate to immutable customer_id | No |
| `WEOS/factory/company_store.py` / `company_workspace.py` / `company_index.py` | ACTIVE | Tenant session + hub | No |
| `WEOS/factory/ledger_store.py` / `master_ledger.py` | ACTIVE LEGACY | Advances → ProjectPaymentLedger later | No |
| `WEOS/factory/quote_share.py` / `pdf_*` / `marqt_pdf.py` | ACTIVE | PDF + public scan | No |
| `WEOS/db/models.py` / `quote_store.py` / `durable_store.py` | ACTIVE LEGACY | Dual PRJ + SQL quotes; merge later | No |
| `WEOS/db/models.py` `Customer.mobile` unique global | ACTIVE LEGACY | Agent-path table; **not** V2 canonical FK. Canonical identities are company-scoped unique | No |
| `WEOS/factory/canonical_customer.py` / `canonical_project.py` | ACTIVE | V2 Batch 3–4 spine (additive) | No |
| `WEOS/db/models.py` CanonicalCustomer / CustomerIdentity / CanonicalProject | ACTIVE | Additive SoT tables via create_all | No |
| `WEOS/agent/*` | ACTIVE LEGACY | Product AI dock — **retire later**, not mass-delete yet | No |
| `WEOS/brain/*` | ACTIVE LEGACY | Brain APIs — retire later | No |
| `WEOS/memory/*` | ACTIVE LEGACY | Deterministic memory libs + mutating APIs; strip product surfaces later | No |
| `WEOS/learning/*` | ACTIVE LEGACY | Learning/builder — validate published products before retire | No |
| `WEOS/_smoke_*.py` | TEST-ONLY | Baseline smokes | No |
| `WEOS/memory/smoke_test.py` | TEST-ONLY | Memory suite | No |
| `run_factoryos.py` (repo root if present) | UNKNOWN | Target doc: ARCHIVE candidate; package may be absent | No until A–H |
| Root `cad_engine/` / `app/` (if present) | UNKNOWN / KEEP EXTERNAL | Separate entry points — do not delete for name overlap | No |
| `knowledge_base/memories`, brain cache, commercial agent observations | UNKNOWN | AI out of product scope; archive after validation | No |
| `knowledge_base/libraries/*` | ACTIVE / KEEP EXTERNAL | Seed libraries | No |
| `WEOS/factory/canonical_customer.py` / `canonical_project.py` | ACTIVE | V2 identity spine (B3/B4) | No |
| Old Agent `customers.mobile` global unique | ACTIVE LEGACY | Still present; new path uses company-scoped identities — do not delete yet | No |
| `_tmp_*` directories | UNKNOWN | Local QA artifacts — never commit | N/A |
| `index.html` `#railTools` / `#showerTools` / `#ventTools` / stacked window controls | ACTIVE LEGACY — **PARITY PENDING** | Still required when `WEOS_UNIVERSAL_CANVAS` OFF; B9 wraps/hides when ON — do **not** delete until parity proven | No |
| `#livePreview` legacy preview host | ACTIVE LEGACY — **PARITY PENDING** | Rollback path for Universal Canvas flag OFF | No |

---

## Deletion log

*(empty — no CONFIRMED UNUSED deletions in Batch 0–8)*
