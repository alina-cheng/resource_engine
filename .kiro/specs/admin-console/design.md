# Design: Admin console

- `frontend/admin.js`, `records.js`, `ui.js`; admin routes in `routes_app.py`.
- Import tables distinguish fully held sources, partially imported sources and invalid objects. Long import/maintenance/reindex controls use job ID polling rather than synchronous Web execution. Direct edits include expected_version for conflict protection; login dialogs support first-password and MFA challenges.
- Imports view: "Upload a file" card posts multipart (`api(..., { form })`) to `POST /api/admin/imports/upload`; the run appears in the runs/quarantine tables. Pipeline detail is in the hsds-ingest spec.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
