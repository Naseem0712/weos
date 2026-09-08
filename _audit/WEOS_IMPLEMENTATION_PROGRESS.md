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
| **Commit** | *(filled after commit)* |
| **Push** | *(filled after push)* |
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
| **Issues** | *(filled during impl)* |
| **Commit** | `fix(security): enforce tenant ownership on project and customer routes` |
| **Push** | *(filled after push)* |
| **Rollback** | Revert B1 commit; UI session query is additive |

---

## Remaining batches (from user plan / target doc)

B2+ (architecture): feature flags, Customer/Project SQL tables, DesignDocument adapter, QuoteFamily SoT, Universal Canvas extract, PDF snapshot immutability, ledger migration, AI surface retirement, etc. — only after B0–B1 healthy.
