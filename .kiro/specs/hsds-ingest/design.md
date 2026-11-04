# Design: HSDS ingest

- `app/adapters/base.py` adapter contract (`parse_page`, `native_id`, `map`, `fetch_http`); `registry.py`; `config/sources.json`.
- `app/adapters/odrs.py`, `ndp.py` and `docs/hsds-mapping.md`.
- `app/services/ingest.py`: raw store, atomic per-record transaction, first-version-wins for shared resources, count assertion.
- `app/services/store.py::ingest_upsert`: three-way merge using `resource_source.snapshot`.
- `app/hsds/validator.py`: jsonschema when installed, built-in subset otherwise.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
