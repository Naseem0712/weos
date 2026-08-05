# Learning / catalogue ingest

Learning Engine learns **engineering rules**. It does **not** generate drawings and
does **not** modify production profiles until you explicitly approve.

## Commands

```bash
# Propose from DXF (heuristic geometry) or JSON catalogue stub
python generate.py --learn-propose "Two Track.dxf" --learn-profile-id 29mm_sliding

# List pending proposals
python generate.py --learn-list-pending

# Approve → knowledge_base version snapshot + write profiles/<id>.json
python generate.py --learn-approve <proposal_id> --confirmed-by you

# Reject
python generate.py --learn-reject <proposal_id>
```

## Safety

- Pending files: `knowledge_base/pending/<proposal_id>.json`
- Each review row: `detected_value`, `confidence_percent`, `source`
- Production write only on `--learn-approve`
- Versions: `knowledge_base/profiles/<series>/vN/profile.json`

## Extractors

| Source | Status |
|--------|--------|
| `.dxf` | Heuristic DIMENSION → geometry / dim style candidates |
| `.json` | Catalogue / partial profile / `proposed_rules` |
| `.pdf` / images | Stub API only (no fake OCR) |

See `ARCHITECTURE.md`.
