# Structure
app/adapters (source -> HSDS) · app/hsds (ids, validator, nested views) · app/services (ingest, store, proposals, maintenance, chat, search, documents, seekers, users, llm, website, extract) · app/web (routes) · app/jobs (runner, CLI) · frontend (SPA) · tools/sample_data_generator · tests · infra/terraform · docs · .kiro/specs
Add a source: new adapter + registry entry + config/sources.json entry. Add an endpoint: route in app/web, logic in app/services, test in tests/.
