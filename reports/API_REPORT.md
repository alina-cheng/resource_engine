# API Verification Report — Resource Engine

**Repository:** `alina-cheng/resource_engine` · **Branch:** `feature/api_updates`
**Tested by:** automated harness (`reports/api_check.py`) against a seeded local instance
**Backend profile:** SQLite, mock LLM, in-memory search, local blob store, local auth (`GET /api/health`)
**Dataset:** 300 services / 209 organizations / 366 service-at-locations / 299 locations / 254 taxonomy terms / 3 taxonomies, generated and loaded by `python -m app.demo --reset`.

> How to reproduce: `uv venv --python 3.12 .venv && uv pip install -r requirements-dev.txt`,
> then `DATA_DIR=/tmp/reapi python -m app.demo --reset --no-serve`, start with
> `DATA_DIR=/tmp/reapi PORT=8102 python -m app.main`, and run
> `PYTHONPATH=. python reports/api_check.py http://127.0.0.1:8102 reports/api_check_results.json`.
> Raw per-call results are in `reports/api_check_results.json`.

## 1. Summary

- **Unit tests:** 57 / 57 pass (`python -m unittest`).
- **API harness:** 428 / 439 checks matched expectations. The 11 that did not are **findings about the application**, not harness errors; each is listed in section 5.
- **HSDS conformance:** every record served by `/hsds/*` validates against the repo's vendored HSDS 3.2.3 schema — 0 invalid out of 1,431 records across six object types (validator engine: `jsonschema`).
- **Access control:** 172 negative checks (no-token, wrong-role, revoked-key, forged/expired/tampered tokens) behaved as expected, with one important exception (the default JWT secret — finding F3).

| Group | Checks passed |
|---|---|
| Auth & public | 19 / 21 |
| Seeker | 9 / 9 |
| Provider | 22 / 22 |
| User reports (branch feature) | 6 / 6 |
| Admin | 69 / 70 |
| HSDS API | 67 / 67 |
| Access control | 171 / 172 |
| Robustness | 65 / 72 |
| **Total** | **428 / 439** |

## 2. Endpoint inventory (61 routes)

Auth legend: **key** = `re_` API key; **admin/provider/seeker** = role login token; **any** = any logged-in user; **none** = unauthenticated.

### HSDS API — external, read-only (auth: key; admin login also accepted)
| Method | Path | Notes |
|---|---|---|
| GET | `/hsds/` | API info, HSDS version 3.2.3, OpenAPI link |
| GET | `/hsds/services` | Page wrapper; filters `page, per_page, search/q, status, organization_id, modified_after, taxonomy_term_id, taxonomy_id, minimal, extensions` |
| GET | `/hsds/services/{id}` | fully nested service; 404 if unknown/out of scope |
| GET | `/hsds/organizations`, `/organizations/{id}` | |
| GET | `/hsds/service_at_locations`, `/service_at_locations/{id}` | |
| GET | `/hsds/locations`, `/locations/{id}` | |
| GET | `/hsds/taxonomies` | no `/{id}` route (404) |
| GET | `/hsds/taxonomy_terms`, `/taxonomy_terms/{id}` | |

### Public (no auth)
`GET /api/health` · `POST /api/auth/login` · `POST /api/auth/register` · `POST /api/chat` · `GET /api/chat/history` (no auth — see F6)

### Seeker (login) · Any logged-in user
`GET /api/auth/me` (any) · `GET /api/search` (any) · `GET,PUT /api/seeker/profile` · `GET /api/seeker/requests` · `POST /api/chat/resume` · `POST /api/chat/confirm`

### User reports — new on this branch (any logged-in user / admin)
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/reports` | a signed-in user flags a listing; forces a fresh AI check and raises `user_reported` |
| GET | `/api/admin/reports` | admin lists open reports |
| POST | `/api/admin/reports/{report_id}/resolve` | admin resolves a report |

### Provider (provider login)
`GET /api/provider/organization` · `GET /api/provider/records/{rid}` · `GET,POST /api/provider/change-requests` · `GET /api/provider/needs` · `GET /api/provider/served` · `POST /api/provider/requests/{rid}/respond` · `GET,POST /api/provider/documents`

### Admin (admin login)
`GET /api/admin/stats` · `GET /api/admin/seekers`, `/seekers/{uid}` · `GET /api/admin/providers`, `/providers/{org_id}` · `GET,PUT /api/admin/records/{rid}` · `GET /api/admin/change-requests` · `POST /api/admin/change-requests/{cid}/approve|reject` · `POST /api/admin/maintenance/run` · `GET /api/admin/maintenance/results`, `/maintenance/runs` · `POST /api/admin/imports/run` · `GET /api/admin/imports` · `GET /api/admin/quarantine` · `GET,POST /api/admin/api-keys`, `DELETE /api/admin/api-keys/{kid}` · `GET,POST /api/admin/users` · `GET,POST /api/admin/documents`, `POST /api/admin/documents/{did}/decide` · `POST /api/admin/reindex`

## 3. What was verified (behaviour, not just status codes)

**HSDS API**
- Page wrapper is internally consistent on every list (`total_pages == ceil(total/per_page)`, `size == len(contents)`, `empty`, `first_page`, `last_page`).
- Walking all 12 pages of `/hsds/services` returns each of the 300 services exactly once, with no overlap between consecutive pages.
- `per_page` is capped at 100 (requesting 1000 returns 100).
- Filters work and combine with AND: `organization_id` returns only that org's services; `status`; `modified_after` (future → empty page, past → all 300); `taxonomy_term_id`.
- `minimal=true` returns a smaller record; `extensions=true` adds `x_resource_engine`, which is hidden by default.
- **Source scoping (R3.4):** a key scoped to `odrs` and a key scoped to the other source partition the data exactly (`odrs + other == all`); every record returned to the odrs key is from odrs; asking the odrs key for another source's service or organization returns **404** (no disclosure), and the correctly-scoped key gets 200.
- Every served record validates against the vendored HSDS 3.2.3 schema (0/1,431 invalid).

**Review / maintenance workflow**
- Provider files a change request → appears in the admin queue → admin approves → the new value is immediately served by the HSDS API, and record history records who approved it and the old→new values.
- Approving a second change based on a now-stale value is blocked with **409** (stale detection); it can then be rejected.
- Admin direct edit that would break HSDS is blocked with **422** and leaves the record unchanged.
- Running the AI check on one service gives it a category and a `checked_at`; the run is recorded in maintenance history.

**Ingest**
- Re-running the import does not create duplicates (service count unchanged).
- Every finished import run balances: `received == stored + quarantined`.

**User reports (branch feature)**
- Report requires login; a seeker can file one and it returns an id + "status: open"; it appears in the admin list; admin can resolve it.

**Access control**
- Every `/api/*` route: no token → 401, wrong role → 403.
- Every `/hsds/*` route: no key → 401, unknown key → 401, seeker login token → 401.
- Revoked API key stops working immediately.
- Forged tokens rejected: wrong secret, expired, `alg=none`, and a seeker token with `role` edited to `admin`.
- An API key is not accepted on `/api` routes; an admin login token is accepted on `/hsds`.
- `/hsds` is read-only: POST/PUT/DELETE are not available.

## 4. Non-functional observations

- **Latency** (local, 30 samples, p50/p95 ms): services list 8/9, minimal list 3/3, by-id 3/3, search 10/10, admin results 4/5. Fast on the demo dataset.
- **Search** is recall-heavy: `diapers` matches 196 of 300 and only 1 of the top-10 actually contains the term; `rent`, `legal`, `food` look reasonable; `dental`/nonsense correctly return 0. This is the in-memory backend; OpenSearch is a separate backend.
- **Response headers:** no `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, or HSTS on any response; `Server` header reveals `Werkzeug/…` (Flask dev server).

## 5. Findings

| # | Severity | Finding | Evidence |
|---|---|---|---|
| F1 | **High** | **Default JWT secret accepted.** A token signed with the published default `dev-only-change-me` is accepted as a valid admin. `JWT_SECRET` defaults to that literal in `app/config.py` with no startup guard. If ever run with the default secret and reached over a network, anyone can forge an admin token. | `GET /api/admin/stats` with a self-signed admin token → **200** |
| F2 | Low–Med | **No brute-force throttling / lockout.** 15 consecutive wrong passwords all return 401 (never 429); a valid login still succeeds afterward. | `bruteforce_codes = {401: 15}` |
| F3 | Low–Med | **Unhandled 500 on page overflow.** A huge `page` value (e.g. `?page=99999999999999999999`) throws a 500 (SQLite integer overflow) on list endpoints instead of a clean 400. Affects `/hsds/{services,organizations,service_at_locations,locations,taxonomy_terms}` and `/api/admin/{providers,maintenance/results}`. | 7 of the 14 "odd query" probes returned 500 |
| F4 | Low | **Duplicate email returns 401, not 4xx-conflict.** `POST /api/auth/register` and `POST /api/admin/users` with an existing email return **401** with a correct message ("account already exists"), because the error flows through the auth-error handler. Misleading status for clients. | register existing email → 401 |
| F5 | Low | **No security headers** on API responses (see section 4). | `headers` metric all null |
| F6 | Info | **`GET /api/chat/history` is unauthenticated.** It takes a `session_id`; an unknown session returns an empty list (no leak observed), but by-id access is open — confirm this is intended. | route table, 200 without token |

Notes: the README already states local auth is demo-only and the HSDS schemas are a vendored subset (run `make schemas` for the official files), so F1/F5 are partly expected for local mode — but F1 deserves a hard guard before any external exposure.

## 6. How to explore the API yourself

An interactive console was added at **`/console.html`** (served by the app). Open
`http://<host>:8102/console.html`, log in (`admin@demo.org` / `demo-admin-1`), click **Mint**
to create an API key, pick any endpoint, and **Execute** — it shows the request line, status,
timing, and JSON response, and handles login-token vs API-key auth for you.
