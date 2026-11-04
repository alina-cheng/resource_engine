# Design: Change history and approvals

- `change_history` follows the HSDS metadata shape; microsecond timestamps keep order.
- `change_request` kinds: provider_update, ai_finding, conflict. Patch format `{field: {current, proposed}}`.
- `app/services/proposals.py` (create, stale check, approve, reject) and `HsdsStore.apply_patch`.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
