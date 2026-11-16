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
