# WEOS AI Blueprint — Intelligence Layer

**Product:** WEOS v2.0.0  
**This file:** target architecture for WEOS AI, mapped onto **what the code actually does today** (16 Aug 2026, after `c20bf74`).  
**Companion:** `WEOS/BLUEPRINT.md` is the engineering + ERP truth. This file is the intelligence layer on top of that truth.

**Not a promise sheet.** A dock labelled “WEOS Agent” and a `brain.generate()` function do **not** mean a high-end LLM agent is operational.

---

## 0. The law (non-negotiable)

```
             AI
              │
       understands / reasons
              │
              ▼
       WEOS ENGINE
              │
       calculates / validates
              │
              ▼
       APPROVED DATA
              │
              ▼
        AI RESPONSE
```

| Role | Who | What they may do | What they must not do |
|---|---|---|---|
| **Truth** | Factory engineering engines (`pipeline.py`, glass / hardware / weight / pricing) | Calculate glass size, weight, BOM, cut-list, price | Invent millimetres |
| **Memory** | Knowledge Base + Memory store | Hold approved rules, observations, catalogues | Auto-write production products |
| **Intelligence** | Context + Agent + Suggestion | Read structured context, call **tools**, explain, warn, recommend | Bypass engines, mutate a quote snapshot without user Accept, declare a pattern “mandatory” |

**AI is not a calculator.**  
User says: *Width 2400, height 2100, 2-track sliding, 8mm glass.*  
Engine calculates glass area / weight / profiles / hardware / BOM / price.  
AI **reads that result** and says:

> Suggestion: 2400 × 2100 opening, 2-track, 8mm toughened is available. Calculated glass weight is **X kg**. Premium roller is **not** selected.

If the numbers in that sentence did not come from an engine tool, the sentence is a bug.

---

## 1. Two brains (do not mix them)

| Brain | What it is | Status today |
|---|---|---|
| **Engineering brain** | Deterministic product JSON + `generate_job` pipeline | **Substantial and live** — this is how quotes are actually built |
| **AI / Agent brain** | Intelligence layer: context, suggestions, learning, (future) LLM orchestration | **Foundation only** — rules + heuristics + extract/approve. **No LLM.** |

Folder names already exist (`WEOS/brain/`, `WEOS/agent/`, `WEOS/learning/`, `WEOS/memory/`). That is **architecture scaffolding**, not proof of autonomous reasoning.

---

## 2. Target stack

```
                         ┌──────────────────────┐
                         │       WEOS AI        │
                         │   Intelligence Layer │
                         └──────────┬───────────┘
                                    │
                 ┌──────────────────┼──────────────────┐
                 │                  │                  │
                 ▼                  ▼                  ▼
          CONTEXT ENGINE       AGENT ENGINE       KNOWLEDGE ENGINE
                 │                  │                  │
          Current Quote        Reasoning         Company Knowledge
          Customer             Suggestions       Engineering Rules
          Product              Warnings          Old Quotes
          Dimensions           Actions            PDFs
          BOM                  Questions          Catalogues
                 │                  │                  │
                 └──────────────────┼──────────────────┘
                                    ▼
                           ENGINEERING ENGINES
                                    │
          ┌─────────────┬───────────┼────────────┬─────────────┐
          ▼             ▼           ▼            ▼             ▼
       Geometry       Glass       Hardware     Weight        Pricing
          │             │           │            │             │
          └─────────────┴───────────┼────────────┴─────────────┘
                                    ▼
                              QUOTE / BOM
                                    │
                      ┌─────────────┼─────────────┐
                      ▼             ▼             ▼
                    Preview         PDF          Factory
```

**Invariant:** arrows from AI into engines go through **named tools**. AI never opens the database or rewrites `product.json`.

---

## 3. What exists today vs what this document specifies

### 3.1 Live today (code paths)

| Piece | File | What it actually does |
|---|---|---|
| Quote pipeline (truth) | `WEOS/factory/pipeline.py` → `generate_job` | geometry → glass → hardware → brush → track → materials → cut-list → weight → BOM → quotation |
| Immutable line snapshot | `WEOS/factory/quote_item_snapshot.py` | Frozen product/glass/hardware/calc at add time; refresh must not silently substitute another product |
| Live Agent orchestrator | `WEOS/agent/orchestrator.py` `analyze()` | Runs **deterministic** suggestion rules; writes observation; optional persist to `quote_suggestions` |
| Suggestion rules | `WEOS/agent/suggestion_engine.py` `generate()` | Handles-per-shutter, glass thickness allow-list, track vs shutter, laminated/DGU notes, etc. **No LLM.** |
| Agent UI dock | `WEOS/website/index.html` `weosRunAgent()` | POST `/api/agent/analyze` with current cart line; Apply/Ignore **records status**, does not yet mutate the live cart |
| Engineering Brain | `WEOS/brain/engine.py` | Loads **approved** memory, compatibility/conflict checks. `generate()` builds a **simplified** BOM from perimeter/area — **not** the factory pipeline |
| Learning Engine V2 | `WEOS/learning/engine_v2.py` | Upload → extract → pending → approve → KB version. `autoWriteProduction: False` |
| PDF extract | `WEOS/learning/pdf_catalogue.py` | **pypdf / pdfplumber text heuristics.** Not vision OCR, not an LLM |
| DXF extract | `WEOS/learning/extract.py` | Dimension clustering heuristics. Does not copy DXF into production drawings |
| Memory store | `WEOS/memory/store.py` + `schemas.py` | 11 namespaced JSON memory types; draft → pending_approval → approved |
| Commercial observe | `WEOS/learning/commercial_agent.py` | Frequency / customer prefs / margin observations. Never auto-writes engineering |
| Engineering observe | `WEOS/learning/engineering_agent.py` | Observes calc/cart; suggestions go to **pending review** |
| Older quote store wiring | `WEOS/api/server.py` `/api/quotes*` | Agent runs on create / update / finalize of the **SQL quote table** path |

### 3.2 Not established (do not claim)

- No OpenAI / Anthropic / Ollama / LangChain (or any LLM SDK) in this repo.
- No tool-calling loop (`read_quote` → `calculate()` → `validate_quote`).
- No natural-language “banado 2 windows 1500×1200” orchestrator.
- Brain `generate()` is **not** a substitute for `pipeline.generate_job`. Mixing them would hallucinate millimetres.
- Learning / memory / agent HTTP routes are **global**, not GST-tenant scoped (`BLUEPRINT.md` §14.13).
- Agent “Apply” on the dock does **not** create a new quote version from a suggestion.

---

## 4. Context Engine — AI’s eyes

AI must **not** receive the whole database on every call.

### Target context pack (one JSON object)

```json
{
  "companyGst": "36ARWPA9740L1Z3",
  "customer": { "name": "", "mobile": "" },
  "projectId": "PRJ-…",
  "quotationId": "",
  "quoteVersion": 1,
  "product": "29mm Sliding Window",
  "seriesId": "29mm_sliding",
  "width": 2400,
  "height": 2100,
  "tracks": 2,
  "shutters": 2,
  "glass": "8mm Toughened",
  "colour": "Black Texture",
  "quantity": 4,
  "profiles": [],
  "hardware": [],
  "bom": {},
  "rates": {},
  "engineResult": {},
  "warnings": [],
  "similarQuotes": [],
  "approvedRules": []
}
```

AI reasons **only** on this pack + tool results.

### Current code

`weosAgentCtx()` and `_quote_to_context()` already send a **thin** slice: product, series, W/H, qty, tracks, shutters, colour, glass, hardware, rates. They do **not** yet attach engine BOM, similar quotes, or approved-rule versions.

**Target gap:** Context Engine should assemble the pack from:

1. Logged-in company session (GST).
2. Current project + selected cart line **snapshot**.
3. Last `generate_job` / live price result (numbers already calculated).
4. Compact similar-quote hits from **this GST only** (index, not a full scan).
5. Approved KB handles that apply to this series (ids + versions, not the whole library).

---

## 5. Knowledge Engine — five layers

```
APPROVED KNOWLEDGE          ← production may use
       ↑
REVIEWED KNOWLEDGE          ← admin edited the extract
       ↑
AI EXTRACTED KNOWLEDGE      ← candidate only
       ↑
DOCUMENT KNOWLEDGE          ← PDF / Excel / DXF / image text
       ↑
RAW INPUT                   ← upload bytes
```

### Law

PDF in → extract → **candidate** → confidence → **admin review** → approve → WEOS Knowledge → engines/quotes may use.

**AI must not promote a candidate into a production engineering rule.**

This is already the Learning Engine V2 contract:

```
Extract → Review → Approve → Knowledge Base Version → Production (manual via Product Builder)
autoWriteProduction = False
```

Files: `WEOS/learning/engine_v2.py`, `WEOS/learning/knowledge_base.py`, `knowledge_base/pending/v2/`, `knowledge_base/versions/vN/`.

### Example (target behaviour)

Upload an old quotation PDF. Extract may find:

- Product: Sliding Window  
- Profile: 29mm  
- Glass: 8mm Toughened  
- Powder: Black Texture  
- Payment: 50% Advance  
- Warranty: 2 Years  

That row is **pending**. Production 29mm glass rules do not change until an admin Approves, and even then **Product Builder / explicit publish** writes the live product — not the extractor.

Today’s extractor is **regex + table text**, not a language model. An LLM may later fill the extract step; the **gate stays the same**.

---

## 6. Memory Engine — do not dump one database

Memories stay **namespaced**. Current types in `WEOS/memory/schemas.py`:

| Target bucket (this blueprint) | Current memory types | Notes |
|---|---|---|
| **A. Company memory** | (not a first-class type yet) | Preferences, terms, branding, default payment, preferred series/glass/hardware. **Must be keyed by GST.** Today company profile JSON holds branding; commercial prefs are global files |
| **B. Product memory** | `product`, `profile`, `hardware`, `glass` | Series, compatibility, allow-lists |
| **C. Engineering memory** | `engineering`, `formula`, `drawing`, `factory` | Weight, glass sizing, cut-list, packing |
| **D. Commercial memory** | `commercial`, `quotation` | Rates, markup, labour, GST, discount patterns, quotation language |
| **E. Conversation / agent memory** | `learning` | User asked / AI suggested / accepted / rejected. Today: observations JSONL + `write_observation_as_learning` |

**Hard rule (from ERP blueprint):** do not share one factory’s formulas into another GST workspace. Tenant key is missing on learning/memory APIs today — that is a **blocker** before any LLM sees memory.

---

## 7. Agent Engine — tools, not database access

### Target tool belt

| Tool | Calls | Returns |
|---|---|---|
| `read_quote()` | project + version snapshot | Structured quote, no other companies |
| `read_product()` | `WEOS/products/<id>/` | Product JSON + rules |
| `read_customer()` | ledger/customer for **this GST** | Name, mobile, billed, balance |
| `read_profile()` / `read_glass()` / `read_hardware()` | catalogues + approved memory | Allow-lists, kg/m, thickness |
| `calculate()` | `pipeline.generate_job` | Full engine result |
| `calculate_weight()` | `weight_engine` | kg + derivation |
| `calculate_bom()` | pipeline BOM stage | Lines |
| `calculate_price()` | live pricing | taxable / GST / grand |
| `compare_quotes()` | this GST index | Diff of two snapshots |
| `search_knowledge()` | approved KB only | Hits + version |
| `search_old_quotes()` | this GST, compact index | Similar W×H / series / glass |
| `validate_quote()` | brain compatibility + engine warnings | errors / warnings |
| `create_suggestion()` | suggestion engine | cards for the UI |

Flow:

```
AI  →  Tool  →  WEOS Engine  →  Validated Result  →  AI
```

### Current code

There is **no** tool registry. `analyze()` calls `suggestion_engine.generate(context)` in-process. Brain `generate()` approximates BOM from `2*(W+H)` perimeter — **unsafe as a quote engine**. Until tools exist, keep Brain generate **off** the live cart.

### Hallucination fence

If the model says “glass weight is 42 kg” and `calculate_weight()` returned 38.6, the UI must show **38.6** (engine) and treat the model line as a defect. Never print the model number without a tool citation.

---

## 8. Suggestion Engine — quote-time help

This is the layer for: *“Quote banate waqt mujhe suggestion dikhni chahiye.”*

### Triggers (already coded in `WEOS/agent/orchestrator.py`)

`product_select` · `series_select` · `dimension_change` · `track_change` · `shutter_change` · `glass_change` · `hardware_change` · `colour_change` · `bom_calc` · `price_calc` · `finalize`

### Target examples (engine numbers inside the sentence)

- 5mm Clear → 8mm Toughened: *Glass weight increased from **X** kg to **Y** kg; material amount changed by ₹**Z**.* (X/Y/Z from `calculate_weight` + `calculate_price`, not guessed.)
- Laminated 6 + 1.52 + 5: *Total 12.52 mm. Confirm the selected profile accepts this glazing thickness.* (allow-list from product glass rules / Brain compatibility.)
- Louver: *BOM still contains a window-frame component. Verify louver profile mapping.* (validate against product id + BOM roles.)

Agent may **detect** mapping bugs; it does not silently rewrite the data model. Underlying product JSON must still be correct.

### Current behaviour

Rules in `suggestion_engine.py` are real and useful (handles, glass mm, track/shutter). They do **not** yet attach live weight delta or ₹ delta from the factory pipeline. Dock “Apply” records accepted/rejected on the **old quote table**, not a new ERP quote version.

---

## 9. AI + Quote architecture

```
                    CUSTOMER
                       │
                       ▼
                    PROJECT
                       │
                       ▼
                  QUOTE VERSION
                       │
                       ▼
                IMMUTABLE SNAPSHOT
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
          ENGINE     MEMORY     AGENT
             │         │         │
             └─────────┼─────────┘
                       ▼
                  RESOLVED DATA
                       │
             ┌─────────┼──────────┐
             ▼         ▼          ▼
            BOM       PRICE      PREVIEW
             │         │          │
             └─────────┼──────────┘
                       ▼
                      PDF
```

**AI must not modify a quote snapshot without user approval.**

```
AI:  "I recommend changing glass to 8mm."
User: Accept
     → new quote version (new snapshot)
     → engine re-runs
     → PDF from the new snapshot
```

Reject / Ignore: snapshot unchanged; conversation memory records the rejection.

Today: `quote_item_snapshot.py` already freezes the line. The missing piece is **Accept → clone version → re-pipeline**. Do not PATCH the frozen glass field in place.

---

## 10. Learning loop (safe)

```
              USER ACTION
                   ↓
              QUOTE DATA
                   ↓
              OBSERVATION
                   ↓
             AI ANALYSIS
                   ↓
          ┌────────┴────────┐
          │                 │
       Known             New Pattern
          │                 │
          │                 ▼
          │             Candidate
          │             Knowledge
          │                 ↓
          │               Review
          │                 ↓
          │              Approve
          │                 ↓
          └──────────→ KNOWLEDGE BASE
                           ↓
                     FUTURE SUGGESTION
```

**Safe example:** 83 approved quotes used 29mm Sliding + 8mm Toughened + Black Texture.

AI may ask:

> This combination appears in 83 approved quotes. Save as a **recommended default**?

AI may **not** declare: “8mm is mandatory.”

Today: `commercial_agent` / `engineering_agent` already count frequencies and emit suggestions with `oneClick` → pending. They do not auto-approve. Keep that gate when an LLM is added.

---

## 11. PDF intelligence

**Target:** structured extraction, not copy-paste.

```
Company format → quotation format → product descriptions → terms
→ payment → warranty → material terminology → customer language
```

Then on a new quote: *“Use this company’s established description for this product.”*  
Source = approved quotation memory for **this GST**, not the last PDF blob.

**Today:** `pdf_catalogue.py` + `quotation_learn.py` pull text/tables and pattern-count warranty/payment phrases. Templates are **never auto-overwritten**. Vision LLM can later improve extract quality; approve-gate stays.

---

## 12. Natural-language orchestrator (future, not current)

User: *“Is 2400×2100 sliding window ka quote bana do.”*

```
Understand request
       ↓
Identify product          → read_product / catalogue
       ↓
Find compatible series    → search_knowledge (approved)
       ↓
Ask missing options       → colour, glass, tracks, qty
       ↓
Geometry / Glass / Hardware / Weight / BOM / Pricing
       ↓                   (all engine tools)
Validation
       ↓
Suggestion Engine
       ↓
Quote version (user confirm)
       ↓
Preview + PDF
```

AI = **orchestrator**. Engines = **truth**.

This path is **not implemented**. Do not wire a chat box to `brain.generate()` and call it quoting.

---

## 13. Readiness (honest)

| Layer | Status | Evidence |
|---|---|---|
| Company workspace | 🟢 Strong | Session + PIN; see `BLUEPRINT.md` |
| Project / Quote | 🟢 Strong | durable project JSON + versions |
| Multi-company isolation | 🟢 Tested | dual `_smoke_scale_isolate.py` PASS/PASS |
| FY / ledger | 🟡 Bug | `_smoke_company_ledger.py` FAIL/FAIL (177000 vs 150000) |
| Product calculation | 🟢 Substantial | `pipeline.generate_job` |
| BOM / PDF | 🟢 Substantial | factory + customer PDFs |
| Immutable snapshots | 🟢 Present | `quote_item_snapshot.py` |
| Memory namespaces | 🟡 Foundation | 11 types, JSON files, **not GST-scoped** |
| Knowledge Base + approve gate | 🟡 Foundation | V2 pending/versions; extract is heuristic |
| Suggestion Engine | 🟡 Foundation | Deterministic rules + dock; weak engine-number citations; Apply ≠ new version |
| Agent orchestrator | 🟡 Foundation | `analyze()` + `/api/agent/analyze`; no tool loop |
| Context pack | 🟡 Thin | Line fields only; no BOM/similar/approved-rule bundle |
| High-end LLM reasoning | 🔴 Not in repo | No LLM client |
| Autonomous learning | 🔴 By design off | `autoWriteProduction: False` — keep it |
| Production scale 10k companies | 🔴 Not proven | session O(n companies); fat JSON index |

---

## 14. Harden these before connecting an LLM

From `BLUEPRINT.md` §14, the ones that become **dangerous** if a model can call APIs:

1. Fix ledger smoke (money truth) — AI must not quote wrong billed/balance.
2. GST-scope **every** `/api/learning/*`, `/api/memory/*`, `/api/agent/*` route (session required).
3. Session lookup SQL index (not walk-all-companies).
4. Gate customer profile GET/PUT.
5. PIN lockout; tighten CORS.
6. **Never** let Brain perimeter-BOM serve the live cart.
7. Tenant-key observations (`companyGst` on every learning JSONL row).
8. Tool results only — no raw `list_payloads(kind="project")` into a prompt.

---

## 15. Build order (when implementing this layer)

Do **not** start with a chat LLM.

1. **Context pack v1** — attach last engine result + snapshot ids to `analyze()`.
2. **Suggestion citations** — every 💡/⚠️ card includes engine X→Y kg and ₹Z when those tools ran.
3. **Accept → new version** — Apply clones snapshot, re-runs pipeline, does not PATCH frozen fields.
4. **GST tenant on memory/learning.**
5. **Tool facade** — Python functions with allow-listed args; agent (even deterministic) may only call these.
6. **Optional LLM** — orchestrator that emits tool calls + a user-visible explanation. Model never writes `product.json`.
7. **NL quote create** — only after 1–6 and ledger smoke is green twice.

---

## 16. Related files

| File | Role |
|---|---|
| `WEOS/BLUEPRINT.md` | ERP, isolation, FY, caps, dual tests |
| `WEOS/AI_BLUEPRINT.md` | **This file** — intelligence layer |
| `WEOS/factory/pipeline.py` | Engineering truth |
| `WEOS/factory/quote_item_snapshot.py` | Immutable quote line |
| `WEOS/agent/orchestrator.py` | Live analyze + triggers |
| `WEOS/agent/suggestion_engine.py` | Deterministic suggestions |
| `WEOS/brain/engine.py` | Approved-KB reasoner (not live quote engine) |
| `WEOS/learning/engine_v2.py` | Extract → review → approve |
| `WEOS/memory/schemas.py` | Memory types + approval statuses |

---

*If the code changes, update §3 and §13. If an LLM client is added, this file must say which provider, which tools it may call, and that `autoWriteProduction` is still False.*
