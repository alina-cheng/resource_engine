# Test plan

Run: `make test` (stdlib `unittest`; `pytest` also discovers the tests). 40 tests, about 12 seconds, no network.

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
PostgreSQL, Cognito, S3, Bedrock, OpenSearch, Textract, live website fetching, ECS job runner, Terraform apply. Use the `docker compose --profile pg` stack for PostgreSQL and a sandbox AWS account for the rest.

## Evaluation caveat
The maintenance evaluation uses synthetic pages written in the extractor's own vocabulary. It guards against regressions but is not evidence of real-world accuracy. Build a labelled set from real pages before relying on the numbers.
