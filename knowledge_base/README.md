# Manufacturing Knowledge Base

Flow: **Extract → Review → Approve → Knowledge Base Version → Production (manual)**

Learning Engine never auto-writes production products or profiles.

See also: [`WEOS/MEMORY_ARCHITECTURE.md`](../WEOS/MEMORY_ARCHITECTURE.md) — Manufacturing Memory + Engineering Brain.

## Layout

- `profiles/<series>/vN/` — immutable version snapshots of approved engineering profile JSON (legacy V1 path)
- `pending/` — legacy learning proposals; `pending/v2/` — Learning Engine V2 queue
- `libraries/` — approved Product Series / Profiles / Hardware / Glass / Formulas / Templates / Quotation patterns
- `versions/vN/` — immutable KB snapshots after admin approve (**rollback source**)
- `memories/` — Manufacturing Memory namespaces (engineering, commercial, drawing, factory, learning, …) + search index + Brain cache
- `uploads/` — source PDFs/images for review (`uploads/crops/` for page previews)
- `pipeline/hooks.json` — continuous-learn source hooks (factory/customer feedback scaffolded)
- `commercial/` — quote observations, intelligence cache, `customer_memory/` profiles
- `engineering/` — engineering observations JSONL, formula refinements, insights
- `hardware_library/` / `glass_library/` — legacy stubs

## Admin UI

Open **Learning Engine** in the WEOS website:

1. Upload a catalogue PDF / old quote / JSON
2. Fix fields on the Review card
3. Approve → libraries + KB version
4. Product Library Tree + Product Builder load approved series
5. **Engineering Live** — observation stream, insights, material weight compute
6. **Commercial Intel** — margins, seasonal, dealers, Customer Memory lookup
7. **AI Suggestions** — one-click queues Pending Review (never silent production overwrite)
8. **Memory & Brain** — browse 11 memories, search, Brain load/generate, KB rollback

### Customer Memory

On Window Cart, when a known customer is entered, WEOS asks (Hindi prompt) whether to apply previous commercial settings. Apply requires explicit confirm — engineering production rules are never auto-written.

### Rollback

`POST /api/memory/versions/rollback` restores `libraries/` from `versions/vN` and publishes a new auditable version. Production products are never modified.
