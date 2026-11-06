# Design: HSDS REST API

- `app/web/routes_hsds.py`; `app/hsds/nest.py` builds nested views with page-level prefetch.
- `api_key` table (sha256, prefix, scope, last used, revoked).
- Nested output refreshes offsets from retained IANA/local schedule context and recursively hides x_* extensions unless requested; validation uses official HSDS schemas shared with source transforms.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
