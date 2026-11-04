# Design: HSDS ingest

- `app/adapters/base.py` adapter contract (`parse_page`, `native_id`, `map`, `fetch_http`); `registry.py`; `config/sources.json`.
- `app/adapters/odrs.py`, `ndp.py`: existing transport + richer mapping wrapped by `canonical.py`; original core transforms/IDs and object partitioning in `app/adapters/transform`. `partition.py` restores parent-failure cascade from the original engine. `assemble.py` folds accepted objects into documents.
- `app/services/ingest.py`: raw store, atomic per-record transaction, first-version-wins for shared resources, count assertion.
- `app/services/store.py::ingest_upsert`: three-way merge using `resource_source.snapshot`.
- `app/hsds/validator.py`: mandatory jsonschema with official HSDS 3.2.3 files and the original transform's required-parent/data-quality rules. No handwritten fallback.
- Per-object quarantine supersedes whole-source quarantine for field/object validation failures (user-approved 2026-11-04). The accepted dependency graph is still one write transaction. Unmappable records and failed writes are held as whole records; partial records and held objects have distinct counters and UI labels.
- Schedules carry IANA/local-time context under `x_resource_engine.local_schedule`; `schedule.timezone` must never contain an IANA string. Compatibility migrations preserve preexisting public IDs and append audit history; re-import reuses source-native org/service/location identities.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
