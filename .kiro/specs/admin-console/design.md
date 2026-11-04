# Design: Admin console

- `frontend/admin.js`, `records.js`, `ui.js`; admin routes in `routes_app.py`.
- Import tables distinguish fully held sources, partially imported sources and invalid objects. Long import/maintenance/reindex controls use job ID polling rather than synchronous Web execution. Direct edits include expected_version for conflict protection; login dialogs support first-password and MFA challenges.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
