# Tasks: AI maintenance worker

- [x] Sample website source with seeded failures
- [x] Rule extractor (lists, ranges, languages)
- [x] Categories and evidence-required proposals
- [x] Page-hash skipping and single-record check
- [x] Seeded evaluation with thresholds in tests
- [x] Detection engine ported from the One Degree monorepo into `app/maintenance/` (grounded extractor, structured comparator, review-need hashing) behind a bridge (ADR-9)
- [x] User-report-triggered recheck: `POST /api/reports`, forces a check, single `user_reported` flag, admin Reports view, demo data (ADR-10)
- [x] Preserve missing-field proposal baselines, typed proposals and source-specific schedule/county semantics
- [x] Keep seeded evaluation thresholds unchanged; failure status and proposal-validity regressions covered
- [ ] Live website source (built, untested)
- [ ] Bedrock extractor evaluated on real pages
- [ ] Labelled real-page evaluation set
- [ ] JavaScript-rendered page handling
