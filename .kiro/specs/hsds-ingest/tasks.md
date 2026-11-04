# Tasks: HSDS ingest

- [x] ODRS adapter with mapping table
- [x] NDP adapter against the supplied samples
- [x] Raw store, quarantine and count balance
- [x] Deterministic ids and idempotent re-import
- [x] Three-way reconciliation and conflict requests
- [x] Schedules with UTC offset and timezone
- [x] Import an uploaded file through the pipeline, reusing a source's adapter
- [x] Quarantine demo sample (valid + unmappable NDP records)
- [ ] Replace vendored schemas with official v3.2.3 and fix rejects
- [ ] HTTP transports verified against live ODRS and NDP endpoints
- [ ] Deletion handling for records removed at the source
- [ ] Cross-source deduplication using provenance links
