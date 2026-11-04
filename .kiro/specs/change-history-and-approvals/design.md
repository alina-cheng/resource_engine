# Design: Change history and approvals

- `change_history` follows the HSDS metadata shape; microsecond timestamps keep order.
- `change_request` kinds: provider_update, ai_finding, conflict. Patch format `{field: {current, proposed}}`.
- `app/services/proposals.py` (create, stale check, approve, reject) and `HsdsStore.apply_patch`.
- Restore original conditional pending-request claim and version compare-and-swap. PostgreSQL locks the resource row during the same transaction's stale check/write; SQLite begins a write transaction before baseline reads. Failed validation/staleness rolls back the claimed decision and history. Direct admin UI edits carry expected_version and receive HTTP 409 on conflicts.
- `app/migrations.py` versions workflow upgrades and HSDS compatibility normalization, preserves existing IDs/history, and audits rewritten resource documents. Pending old proposals whose baselines changed still require recheck/explicit review.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
