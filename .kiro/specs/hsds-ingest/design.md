# Design: HSDS ingest

- `app/adapters/base.py` adapter contract (`parse_page`, `native_id`, `map`, `fetch_http`); `registry.py`; `config/sources.json`.
- `app/adapters/odrs.py`, `ndp.py` and `docs/hsds-mapping.md`.
- `app/services/ingest.py`: raw store, atomic per-record transaction, first-version-wins for shared resources, count assertion.
- `app/services/store.py::ingest_upsert`: three-way merge using `resource_source.snapshot`.
- `app/hsds/validator.py`: jsonschema when installed, built-in subset otherwise.
- Ad-hoc file import: `POST /api/admin/imports/upload` (admin only) writes the uploaded JSON to a temp file, builds a `SourceConfig` for the chosen source with that path as `location`, and calls the same `ingest.run`; no adapter changes needed since `base.fetch` already reads a file glob.
- `data/samples/national-data-platform-quarantine-demo.json`: demo source exercising quarantine (2 valid, 3 held back: missing name, missing id, non-integer `yearIncorporated`).

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
