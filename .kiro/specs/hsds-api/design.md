# Design: HSDS REST API

- `app/web/routes_hsds.py`; `app/hsds/nest.py` builds nested views with page-level prefetch.
- `api_key` table (sha256, prefix, scope, last used, revoked).

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
