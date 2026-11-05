# Run locally and visualize

Needs uv and Python 3.12. SQLite demo needs no external database, AWS account or API keys.

## Option A: Python
```bash
uv sync --frozen
make demo            # generates data, loads it, seeds demo users, serves http://127.0.0.1:8000
```
`make demo` runs `uv run --frozen python -m app.demo`: it generates ~236 synthetic source records, imports valid HSDS objects with dependency-aware quarantine, creates demo users, policy documents, help requests and API keys, runs mock maintenance, then serves the app. By default it uses `config/sources.demo.json` and `var/demo`; existing data is preserved. Explicit DATA_DIR, DATABASE_URL and SOURCES_CONFIG overrides take priority, so review them before using `--reset`.

## Real data
Configured imports use `config/sources.json`: ODRS comes from the configured HTTPS API and NDP from the two sample files in `data/samples`. Use only an authorized event/staging ODRS key in `.env` as `ODRS_API_KEY=...` (the app loads this file at startup, and git ignores it), then:
```bash
uv run --frozen python -m app.jobs.run import       # configured sources; no demo users or maintenance
make run                                           # http://127.0.0.1:8000
```
For a synthetic/event dataset, `uv run --frozen python -m app.jobs.run seed-demo --no-maintenance` adds demo accounts and scenarios after importing if the store is empty. Provider logins require matching demo organizations. `sources.json` limits ODRS to one page of 25 records; change `per_page` and `max_pages` deliberately when a larger authorized import is needed.

Use the appropriate website source before maintenance: sample pages do not verify arbitrary imported records. Bedrock seeding requires an explicit `--limit`; `--no-maintenance` always skips checks even when a limit is supplied.

## Option B: Docker
```bash
docker compose up --build                 # SQLite, http://localhost:8000
docker compose --profile pg up --build    # PostgreSQL 16, http://localhost:8001
```

## Demo accounts
| Persona | Email | Password |
|---|---|---|
| Admin | admin@demo.org | demo-admin-1 |
| Provider (Bay Area Diaper Bank) | provider1@demo.org | demo-provider-1 |
| Help seeker | ana@demo.org | demo-seeker-1 |
Providers 2 to 5 follow the pattern `provider2@demo.org` / `demo-provider-2` (Tri-City Rent Relief, Harbor Community Pantry, Eastside Legal Aid, Valley Family Health Clinic).

## A five-minute tour
1. **Anonymous chat.** On the home page ask "How does One Degree work?" (answered), then "I need rental assistance" (asks you to create a profile).
2. **Sign up from the chat**, then see matches. Choose "Send request", accept the sharing prompt.
3. **Provider.** Log in as provider1. Open "Needs & people served", offer support. Edit the organization and send the change for review.
4. **Admin.** Log in as admin. "Review" shows the provider change, AI findings (each with the website evidence) and source clashes. Approve one and open its record to see the change history.
5. **Records** filters by category (actively bad, check failed, discrepancy, missing information, verified). "Check now" re-checks one record.
6. **API keys** → create a key, then `curl -H "Authorization: Bearer <key>" "http://127.0.0.1:8000/hsds/services?search=diapers&per_page=3"`.
7. **Policy question.** Ask "What do I need to bring for the diaper bank?" and see the cited document.
8. **JSON upload.** Admin → Imports → Upload a file uses the selected source's adapter, raw storage, schema validation and quarantine. This accepts source-format JSON, not CSV/XLSX.
9. **API console.** Open `/console.html` to inspect API calls with your own login/API key. The verification harness and its usage are documented in `reports/API_REPORT.md`.

## Useful commands
```bash
make test                                   # pytest; PostgreSQL checks skip without TEST_DATABASE_URL
python -m tools.sample_data_generator --odrs 1000 --ndp 500 --seed 1   # bigger data set
python -m app.jobs.run import               # run an import from the CLI
python -m app.jobs.run maintenance --limit 50 --force
python -m app.jobs.run reindex
```
Set `LLM_BACKEND=bedrock` (with AWS credentials) to use Bedrock for chat answers and website extraction; `WEBSITE_BACKEND=live` to fetch real websites. The defaults need neither.

Set an account-enabled `BEDROCK_MODEL_ID` before choosing Bedrock; no default model is guessed. For PostgreSQL regression tests set `TEST_DATABASE_URL` to a local disposable test database, then run `make test`; each integration test creates/removes its own schema. `scripts/verify_postgres_restart.py prepare|verify` preserves a local receipt around an operator-controlled actual database restart. Do not run test helpers on a production database.
