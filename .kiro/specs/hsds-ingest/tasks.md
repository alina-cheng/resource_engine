# Tasks: HSDS ingest

- [x] ODRS adapter with mapping table
- [x] NDP adapter against the supplied samples
- [x] Raw store, quarantine and count balance
- [x] Deterministic ids and idempotent re-import
- [x] Three-way reconciliation and conflict requests
- [x] Schedules with UTC offset and timezone
- [x] Replace vendored schemas with official v3.2.3 and fix rejects without relaxing schema
- [x] Restore original core transforms/IDs plus valid FINAL enrichment
- [x] Restore object-level and parent-dependent quarantine, separate source/object counts and partial-import UI
- [x] Revalidate combined source transports, uploads, partial imports and PostgreSQL integration (108 tests plus 4 PostgreSQL tests; Docker build and Terraform validation)
- [x] Import an uploaded file through the pipeline, reusing a source's adapter
- [x] Quarantine demo sample (valid + unmappable NDP records)
- [ ] HTTP transports verified against live ODRS and NDP endpoints
- [ ] Deletion handling for records removed at the source
- [ ] Cross-source deduplication using provenance links
