# Run locally and visualize

Needs Python 3.12 only. No database, AWS account or API keys.

## Option A: Python
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
make demo            # generates data, loads it, seeds demo users, serves http://127.0.0.1:8000
```
`make demo` runs `python -m app.demo --reset`: it generates ~236 fake source records, imports them (ODRS + NDP), creates demo users, policy documents, help requests and API keys, runs one AI maintenance pass, then serves the app. It uses `config/sources.demo.json` and its own folder, `var/demo`, so it never touches a real import.

## Real data
Real imports use `config/sources.json`: ODRS comes from the live API and NDP from the two files in `data/samples`. Put the key in `.env` as `ODRS_API_KEY=...` (the app loads this file at startup, and git ignores it), then:
```bash
python -m app.jobs.run seed-demo --no-maintenance   # imports real data if the database is empty, adds demo logins
make run                                            # http://127.0.0.1:8000
```
The admin and help seeker demo accounts work on real data. Provider accounts are not created, because they belong to the fake organizations. `max_pages` in `sources.json` limits ODRS to about 1,000 records; remove it to pull all of them (about 24,000).

Leave out `--no-maintenance` only if `WEBSITE_BACKEND=live` is set: by default the AI check reads fake websites and reports false problems on real records.

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

## Useful commands
```bash
make test                                   # full suite, about 4 minutes
python -m tools.sample_data_generator --odrs 1000 --ndp 500 --seed 1   # bigger fake data set
python -m app.jobs.run maintenance --limit 50 --force
python -m app.jobs.run reindex
```
Set `LLM_BACKEND=bedrock` (with AWS credentials) to use Bedrock for chat answers and website extraction; `WEBSITE_BACKEND=live` to fetch real websites. The defaults need neither.
