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

### Pre-existing failures (not fixed this pass; unrelated ledger/login)

| Smoke | Status | Exact failure | Root cause (summary) | Changed by B3/B4? | Blocks next phase (Floor)? |
|---|---|---|---|---|---|
| _smoke_company_login.py | FAIL | ValueError: Customer Mobile number is not saved for verification. in apply_scanner_status → _verify_last6 | Scanner approve path requires saved customer mobile / last-6; smoke fixture does not persist mobile for verification | No | No |
| _smoke_gst_hub_persist.py | FAIL | billed/balance/taxable/grand mismatch + missing customer/project restore | GST hub ledger aggregation / persist restore against polluted or wrong basis totals | No | No |
| _smoke_gst_workspace.py | FAIL | billed 125000→324500; balance 100000→299500; workspace customers missing | Latest-version billing basis + workspace customer listing | No | No |
| _smoke_project_import.py | FAIL | FAIL: ledger advances 0 (import advances OK; ledger sync miss) | Import commits advances on project but company/master ledger does not receive them | No | No |
| _smoke_company_ledger.py | FAIL | billed 150000→177000; balance 85000→112000 | Company ledger billed includes GST or wrong quote set vs smoke expectation | No | No |
| _smoke_quote_lifecycle.py | FAIL | illed must ignore draft, expected 80000 got 240000.0 | Draft quotes incorrectly included in billed totals | No | No |
| _smoke_master_ledger.py | PASS | — | — | No | No |

---

## Remaining batches (from user plan / target doc)

Floor / DesignDocument / Canvas — **NOT STARTED** (hard stop after B4).

## Checkpoint (current session)

- **Starting HEAD:** 488d9170ffbb105305999a50881cf1175410e1b3 (B2)
- **Ending HEAD:** 2e0a9038a0a99d0cb5cb236596d60efaf42ff0fc (docs) after a69c1cd (B4) / 888bfd2 (B3)
- **Branch:** weos-v2-foundation
- B3/B4 committed and pushed to origin/weos-v2-foundation only
- Unrelated dirty left untouched: product stubs, weos.db, company/profile.json, glass catalogue seed, WEOS/customers/, _tmp_*, railway tomls, blueprint/gap docs, etc.
- Production deployment: **NOT PERFORMED**
- Batch 5 / Floor: **NOT STARTED**
