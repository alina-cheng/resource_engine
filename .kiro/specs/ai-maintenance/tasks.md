# Tasks: AI maintenance worker

- [x] Sample website source with seeded failures
- [x] Rule extractor (lists, ranges, languages)
- [x] Categories and evidence-required proposals
- [x] Page-hash skipping and single-record check
- [x] Seeded evaluation with thresholds in tests
- [x] Detection engine ported from the One Degree monorepo into `app/maintenance/` (grounded extractor, structured comparator, review-need hashing) behind a bridge (ADR-9)
- [x] User-report trigger: `POST /api/reports`, record selected + single `user_reported` flag raised for human review, AI re-reviews only if the page changed (respects hash-skip), admin Reports view, flag shown on records, demo data (ADR-10)
- [x] Self-sizing maintenance schedule: checks/run derived from source count (`ceil(sources/recheck_days)*safety_factor`, optional max), scales to 50k, no hard-coded batch (ADR-11)
- [ ] Shard the maintenance run across N parallel Fargate tasks for high-volume throughput — deterministic `hash(service_id) % shards` partition, `--shards`/`--shard-index` CLI args, EventBridge fan-out; self-sizing per shard (decision 1b, deferred)
- [ ] Live website source (built, untested)
- [ ] Bedrock extractor evaluated on real pages
- [ ] Labelled real-page evaluation set
- [ ] JavaScript-rendered page handling

- [x] Preserve missing-field proposal baselines, typed proposals and source-specific schedule/county semantics
- [x] Keep seeded evaluation thresholds unchanged; failure status and proposal-validity regressions covered
