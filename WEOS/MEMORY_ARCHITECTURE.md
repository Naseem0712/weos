# WEOS Manufacturing Memory Architecture + Engineering Brain

This is **not** chatbot memory. It is an **Engineering Manufacturing Memory System**: continuously learn, organize, version, retrieve, and reuse engineering knowledge — with a hard admin gate before anything reaches production use via the Brain.

## Philosophy

| Role | Allowed |
|------|---------|
| AI / agents | Observe, Suggest, Compare, Explain, Recommend |
| Admin | Approve, Reject, Merge, Version, Rollback |
| Production ERP (`WEOS/products/`) | **Never** auto-written from Memory / Learning / Brain |

**Flow:** Observe → Suggest → Admin Review → Approve → Knowledge Base Version → Production use via Brain

Formulas live as **versioned Formula Memory objects** (history appended). Silent overwrite is forbidden.

---

## Architecture diagram

```mermaid
flowchart TB
  subgraph Sources
    PDF[Catalogue PDF]
    DXF[DXF / drawings]
    QTE[Quotations / Calculate]
    FAC[Factory feedback]
  end

  subgraph Agents["Agents (observe only)"]
    ENG[engineering_agent]
    COM[commercial_agent]
    V2[Learning Engine V2]
  end

  subgraph Gate["Admin gate"]
    PEND[Pending / Learning Memory]
    APPR[Approve / Reject / Merge]
  end

  subgraph KB["Knowledge Base"]
    LIB[libraries/*]
    MEM[memories/* — 11 namespaces]
    VER[versions/v1…vN]
  end

  subgraph Brain["Engineering Brain"]
    LOAD[load context]
    REASON[reason decisions]
    GEN[generate BOM / PDF / quote / cut]
  end

  subgraph Runtime
    BUILD[product_builder]
    CALC[calculate / factory engines]
  end

  PDF --> V2
  DXF --> V2
  QTE --> ENG
  QTE --> COM
  FAC -.-> V2
  ENG --> PEND
  COM --> PEND
  V2 --> PEND
  PEND --> APPR
  APPR --> LIB
  APPR --> MEM
  APPR --> VER
  VER -->|rollback restore| LIB
  LIB --> LOAD
  MEM --> LOAD
  LOAD --> REASON --> GEN
  GEN --> BUILD
  GEN -.->|gradual replace| CALC
```

## Relationship chain

```mermaid
flowchart LR
  C[Customer] --> Q[Quotation]
  Q --> P[Products]
  P --> PR[Profiles]
  P --> H[Hardware]
  P --> G[Glass]
  P --> F[Formula]
  P --> D[Drawing]
  D --> M[Machine]
  M --> FAC[Factory]
  FAC --> COST[Costing]
  COST --> R[Reports]
```

---

## Folder structure

```
WEOS/
  memory/                 # Memory Architecture package
    schemas.py            # JSON models for 11 memory types + ranking helpers
    store.py              # CRUD / namespaces / relationships
    admin.py              # approve / reject / merge / version / rollback
    cache.py              # Brain cache L1 RAM → L2 SQLite → L3 vector/keyword
    ranking.py            # Confidence / Source / Approved / Used / Priority
    explain.py            # ★ Engineering Explanation Engine (traceable proof)
    validate.py           # Pre-generate approved-memory gate
    compatibility.py      # Glass/series allow-list warnings
    conflicts.py          # Hard/soft conflict rules (stop generate)
    graph.py              # Relationship neighbors / tree JSON
    version_diff.py       # KB vN ↔ vM field-level compare
    size_learn.py         # Size-scale + teach-upload suggestions
    search/
      index.py            # Inverted index + keyword/filter search
  brain/
    engine.py             # load / reason / validate / explain / generate
  learning/               # Existing V2 — still the extract/approve path
  api/server.py           # /api/memory/* + /api/brain/*

knowledge_base/
  libraries/              # Approved working set (V2)
  versions/vN/            # Immutable snapshots + rollback source
  memories/               # Dedicated memory namespaces
    … (11 types)
    _rules/               # conflicts.json · compatibility.json
    relationships.json
    _index/inverted.json
    _cache/               # file + brain_cache.sqlite3
```

**Storage choice:** JSON files on disk (same as Learning Engine V2 today). Fits WEOS portability (`WEOS_KB_DIR`). SQLite can be layered later without changing API shapes.

---

## Separate memories (never mixed)

| Memory | Backing | Purpose |
|--------|---------|---------|
| Engineering | `memories/engineering/` | Overlap, cutting, BOM, nesting, waste, usage packs |
| Commercial | `memories/commercial/` + `commercial/` | Customer / margins / GST / prefs |
| Product | `libraries/product_series` (+ overrides) | Series + eng/commercial formulas + notes |
| Profile | `libraries/profiles` | Dims, wall, kg/m, positions, drawings |
| Hardware | `libraries/hardware` | Brand, rate, unit, install, supplier |
| Glass | `libraries/glass` | Thickness, density, overlap, calc formula |
| Formula | `libraries/formulas` + `memories/formula/` | Versioned expression + history |
| Drawing | `memories/drawing/` | DXF/SVG/PDF, dimension/arrow styles |
| Quotation | `libraries/quotation_patterns` | Logo, terms, warranty, brand colours |
| Factory | `memories/factory/` | Machine, packing, bundle/QR, delivery |
| Learning | `memories/learning/` | Observations + frequency suggestions |

---

## Learning pipeline (unified)

1. **Observe** — `engineering_agent` / `commercial_agent` / `POST /api/memory/observe`
2. **Suggest** — Learning Memory `pending_approval` or V2 pending proposal
3. **Admin review** — Learning Engine UI or Memory browser
4. **Approve** — writes libraries / memories; optional `publish_kb_version`
5. **Brain** — `POST /api/brain/load|reason|generate` reads **approved** KB only
6. **Rollback** — `POST /api/memory/versions/rollback` restores `libraries/` from `versions/vN`, then publishes a **new** auditable version

Agents already in-tree (`commercial_agent`, `engineering_agent`, `product_builder`, `material_formulas`) remain the observation / builder layer; Memory + Brain unify retrieval and orchestration.

---

## API surface

### Memory
- `GET /api/memory/status` · `GET /api/memory/types`
- `GET|POST /api/memory/{type}` · `GET /api/memory/{type}/{id}` (list includes **ranking** card)
- `POST /api/memory/{type}/{id}/approve|reject` · `POST /api/memory/{type}/merge`
- `POST /api/memory/observe`
- `GET|POST /api/memory/search` · `POST /api/memory/search/rebuild`
- `GET /api/memory/versions` · `POST .../publish` · `POST .../rollback`
- `GET|POST /api/memory/versions/compare` — field-level KB vN↔vM diff
- `GET /api/memory/meta/relationships` · `GET /api/memory/graph` · `GET|POST .../graph/neighbors`
- `GET|POST /api/memory/conflicts` · `GET|POST /api/memory/compatibility`
- `POST /api/memory/size-compare` · `POST /api/memory/teach-upload` (suggest only)
- `GET /api/memory/cache/status` · `POST /api/memory/cache/invalidate`

### Brain
- `GET /api/brain/status`
- `POST /api/brain/load` · `GET /api/brain/load/{series_id}`
- `POST /api/brain/reason`
- `POST /api/brain/validate` — missing approved Glass/Profiles/Formula/Hardware → no generate
- `POST /api/brain/explain` — ★ traceable proof (steps + memory_refs + formula_version + kb_version)
- `POST /api/brain/compatibility` — e.g. 10mm glass on 5/6/8-only series → warning
- `POST /api/brain/conflicts` — hard block (Premium Handle + Old Roller)
- `POST /api/brain/recommend` — Sliding → Mesh / Mosquito / Restrictor / Safety Lock
- `POST /api/brain/generate` → BOM, drawing, PDF, quotation, weight, cost, packing, machine_cutting, **explain**

---

## Intelligence layers (Brain upgrade)

| Feature | Behaviour |
|---------|-----------|
| **Ranking** | Every item: Confidence %, Source, Approved Yes/No, Used N Projects, Last Used, Priority |
| **Rule priority** | Multiple formulas → highest **approved** `priority` (100 → 80 → 20) |
| **Compatibility** | Declarative allow-lists in `memories/_rules/compatibility.json` |
| **Conflicts** | Declarative hard/soft rules in `memories/_rules/conflicts.json`; hard = stop generate |
| **Explain / proof** | Value + steps + equation + memory_refs + formula_version + kb_version + approval |
| **Validation** | Pre-generate gate; clear `missing[]` list; never silent fail |
| **Graph** | Persist edges in `relationships.json`; neighbors/tree API for UI |
| **Size learning** | Upload / size-compare → Learning Memory + Engineering draft (**never auto-apply**) |

---

## Caching

**3 layers:** L1 in-process RAM → L2 SQLite (`memories/_cache/brain_cache.sqlite3`) → L3 vector/keyword stub (sqlite-vss if installed, else token overlap).

- Keyed by `(series, productType, customer, kbVersion)`
- TTL ~2–3 minutes
- **Invalidated** on approve / version publish / rollback

---

## Search strategy

Pragmatic **inverted index** over all memory namespaces (`knowledge_base/memories/_index/inverted.json`).

Supports queries like:
- sliding systems with 30mm track
- products using Premium Handle
- quotations with Black Texture
- formulas related to Glass Width
- products compatible with Series S29

### Honest gaps
- L3 vector search is a keyword stub unless `sqlite-vss` is installed (same API)
- No OCR/vision catalogue understanding beyond existing heuristic PDF text extract
- Factory engines still primarily read `WEOS/products/*`; Brain is the bridge to gradually replace hardcoded ERP tables
- Full `rules/*.json` packs are not auto-generated from Memory on approve (Product Builder publish remains explicit)
- Graph UI is list/tree JSON (not a full force-directed canvas yet)

---

## Version control + rollback

- Approve → optional snapshot `versions/v{N}/` (immutable)
- Rollback → copy `vN` → working `libraries/`, then **publish v{N+1}** with `action: rollback` (history never rewritten)
- **Compare** → field-level diff (e.g. Track 29→30) via `/api/memory/versions/compare`
- Production products untouched

---

## UI

Learning Engine → **Memory & Brain** tab:
- Memory browser with ranking metadata
- Search box
- Brain load / validate / generate / explain / compat / conflict / recommend
- Explain proof panel
- KB version list + **compare** + rollback
- Memory graph neighbors
- Size-scale compare (suggest only)

---

## Smoke test

```bash
python -m WEOS.memory.smoke_test
```

Covers: observation → suggest → approve → new KB version → Brain load → **validation block** → **explain proof** → **priority pick** → **compatibility warning** → **conflict stop** → **version diff** → **size-compare suggestion** → rollback.
