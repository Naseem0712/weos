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
| `WEOS/factory/panel_fills.py` / `special_schematics.py` | ACTIVE | Louvers/pergola/ACP-style | No |
| `WEOS/factory/project_store.py` | ACTIVE LEGACY | FS+SQL mirror SoT today; migrate later | No |
| `WEOS/factory/customer_store.py` | ACTIVE LEGACY | Name-slug profiles; migrate to immutable customer_id | No |
| `WEOS/factory/company_store.py` / `company_workspace.py` / `company_index.py` | ACTIVE | Tenant session + hub | No |
| `WEOS/factory/ledger_store.py` / `master_ledger.py` | ACTIVE LEGACY | Advances → ProjectPaymentLedger later | No |
| `WEOS/factory/quote_share.py` / `pdf_*` / `marqt_pdf.py` | ACTIVE | PDF + public scan | No |
| `WEOS/db/models.py` / `quote_store.py` / `durable_store.py` | ACTIVE LEGACY | Dual PRJ + SQL quotes; merge later | No |
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
| Product stubs `*_stub/` | ACTIVE LEGACY | Placeholder products in tree; user dirty edits preserved | No |
| `_tmp_*` directories | UNKNOWN | Local QA artifacts — never commit | N/A |

---

## Deletion log

*(empty — no CONFIRMED UNUSED deletions in Batch 0/1)*
