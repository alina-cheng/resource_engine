# Test plan

Run: `uv sync --frozen && make test` (pytest). Current integration: 74 tests passed with PostgreSQL 16 enabled via TEST_DATABASE_URL, including 4 real PostgreSQL checks; without it those 4 tests skip. Original 57 unittest cases remain covered. A fake Cognito/Bedrock response is not a real cloud call.

| Area | File | Covers (requirement) |
|---|---|---|
| Mapping | `tests/test_hsds_ingest.py::MappingTests` | all sample records map to valid HSDS (BR-2); deterministic UUIDs; empty props omitted; schedule offsets; description-gap policies |
| Ingest | `::IngestTests` | counts balance; re-run creates no duplicates (BR-3); raw payload kept as received (BR-1); quarantine not drop (BR-2); every stored record validates; clash surfaced, source-only update applied with history (BR-3, BR-4) |
| Store | `::StoreTests` | who/what/when history (BR-4); invalid edit blocked; protected fields |
| HSDS API | `tests/test_api_personas.py` | key required; HSDS Page shape; nested records validate; key scoped to a source; search (BR-11) |
| Roles | same | seeker/provider/admin boundaries; provider cannot touch another organization (BR-5) |
| Approval | same | provider change needs approval, leaves history; invalid change rejected up front; stale proposal needs force (BR-4, BR-5) |
| Chat | same | anonymous need → profile prompt, no provider data; about question answered; sign-up in chat then resume; consent required before a request; policy answer cites document; crisis message (BR-8, BR-10) |
| Provider view | same | consented needs only; contact hidden until accepted (BR-9) |
| Documents | same | upload pending → approve → used by chat (BR-10) |
| Maintenance | `tests/test_maintenance.py` | seeded evaluation: failures always reported (BR-7); ≥95% overall; ≤5% false flags on clean pages; every proposal has evidence; AI proposals need a human; unchanged pages skipped; single-record check (BR-6) |

## Manual / browser checks
A Playwright script exercised the UI end to end during development (anonymous chat → sign-up → request → provider edit → admin approval). It is not part of the repository's CI; add it if you want UI regression coverage.

## Not covered by automated tests
Live Cognito, S3, Bedrock, OpenSearch, Textract, live data/website fetching, real ECS RunTask and Terraform apply remain unverified. PostgreSQL import/idempotence, edits, approvals, concurrency, migrations and new-connection persistence are tested. Docker image build and Terraform validate were executed locally. An actual database-container restart is verified separately with scripts/verify_postgres_restart.py; record that result in integration-status.md after completion.

`test_reliability.py` covers concurrent decisions, stale/invalid approval rollback, flags migration, missing-phone baselines, typed AI proposals, first-password/MFA response sessions, role assignment, persisted ECS launch failures, parent-cascade isolation, existing public IDs and failed-run cleanup. `test_postgres.py` repeats key invariants against isolated PostgreSQL schemas. Supplied NDP samples retain twenty usable sources with seven quarantined objects across six partial records; both count systems must balance.

## Evaluation caveat
The maintenance evaluation uses synthetic pages written in the extractor's own vocabulary. It guards against regressions but is not evidence of real-world accuracy. Build a labelled set from real pages before relying on the numbers.
