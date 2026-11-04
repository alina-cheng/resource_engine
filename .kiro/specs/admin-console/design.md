# Design: Admin console

- `frontend/admin.js`, `records.js`, `ui.js`; admin routes in `routes_app.py`.
- Imports view: "Upload a file" card posts multipart (`api(..., { form })`) to `POST /api/admin/imports/upload`; the run appears in the runs/quarantine tables. Pipeline detail is in the hsds-ingest spec.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
