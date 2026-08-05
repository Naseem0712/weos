"""
Stub for future product types (casement, folding, …).

1. Add profiles/<series>.json with full rule sections.
2. Implement layout in geometry_engine (or sibling) using named params only.
3. Register a thin ProductGenerator that calls pipeline.generate_job / custom layout.
4. Never hardcode catalogue values in Python; never copy DXF entities.
"""
