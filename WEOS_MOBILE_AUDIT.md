# WeOS mobile and costing audit — initial pass (2026-11-16)

Scope: initial static review of `WEOS/website/index.html`, not a complete repository audit. Production branch is unchanged.

## Fixed on this branch
- Under the <=1000px breakpoint, inspector used `max-height:min(48vh,420px)` with independent scrolling, compressing controls. Remove cap and allow normal page scrolling.
- On mobile, `.inspector-sticky` now participates in normal flow instead of occupying persistent editor viewport space.

## Confirmed code paths / risks to investigate
- `setSellDisplay()` writes the same amount to `liveSell` and `stickySell`; there is no distinct sticky margin/profit presentation.
- `refreshLivePrice()` sets an optimistic local sell, then asynchronously calls `/api/quote/live`. Responses have no obvious request sequence guard in the inspected function; stale responses could overwrite newer input changes.
- `refreshLivePrice()` derives `costN` from `live.cost.total || live.displayAmount || lineCalc.price.total`, mixing possible manufacturing cost and displayed amount fallback. Verify API field semantics before applying a 20% profit rule.
- `profitAmt` comes from the design cost payload, not necessarily `selling - actual manufacturing cost`; don't label it sale profit without verification.
- Dynamic `projMore` HTML is generated in two flows; this is not necessarily a duplicate DOM ID at runtime.
- No duplicate named `function name(...)` declarations found by simple static regex in this HTML file. This does not establish absence of dead code or duplicated logic.

## Next verification
1. Confirm 20% is cost markup (minimum sale = manufacturing cost * 1.20), not 20% margin on sale.
2. Derive sticky status from the same latest quote response and latest sell input; guard against stale async responses.
3. Check all product modes (sliding, casement, railing, shower, ventilator) and add-to-cart/old-quote reopen.
4. Run mobile viewport tests at 320/375/390/430 px and desktop regression checks.
5. Scan Python API, quote-store and factory modules for duplicate routes, stale helpers and unreachable code before removal.


## Repository-wide inventory scan — 2026-11-16
- Inspected complete non-truncated GitHub tree: **798 tracked files** (456 JSON, 236 Python, 73 TXT, one ~1 MB HTML).
- Inspected main UI HTML (~1 MB), `WEOS/api/server.py` (~221 KB), `WEOS/factory/product_setup.py` (~136 KB), `WEOS/db/quote_store.py` (~29 KB), and `.gitignore`.
- Static route declaration scan: **250** `@app/@router` HTTP route declarations in `server.py`; no duplicate method+path pairs found by regex.
- Static Python function declaration scan: no repeated top-level function names in `product_setup.py` or `quote_store.py`. This is not a full dead-code analysis.
- Tracked runtime-looking files: `WEOS/weos.db` (~492 KB) and `knowledge_base/memories/_cache/brain_cache.sqlite3` (~119 KB). Review whether these belong in version control; **do not delete or expose data without inspecting migration/deployment dependencies**.
- Tracked smoke output files (`_smoke_out.txt`, `_test_out.txt`, etc.) are candidates for cleanup after verifying references.
- `.gitignore` excludes `.env`, runtime outputs and logs, but does not currently exclude SQLite database files. Already tracked files are not affected by adding ignore patterns.
- No end-to-end browser run, Python test execution, static type checker or full reachability analysis has been performed in this connector-only scan.

## Additional mobile patch
- Reduced canvas height from up to 72vh to compact responsive viewport units on narrow screens; tools remain in the document scroll flow.
- Preserved desktop layout and existing drawing styles.
- Selling rate refresh no longer auto-repopulates a deliberately blank field in the four identified live-pricing code paths. Other flows still need regression tests.

## Priorities
1. Verify mobile viewport screenshots and touch controls; compare against old design.
2. Implement profit/loss sticky status using verified manufacturing cost and explicit user selling amount.
3. Verify blank/zero selling rate in API and cart persistence (including old quotes and all product types).
4. Protect against stale live pricing API responses.
5. Review tracked databases and smoke outputs for safe cleanup.
