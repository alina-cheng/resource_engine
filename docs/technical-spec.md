# Technical Specification

## 1. Stack
| Concern | Choice | Notes |
|---|---|---|
| Language / web | Python 3.12, Flask 3, gunicorn | ADR-1: chosen so the whole API could be tested in the build environment. Routes are thin; FastAPI port is mechanical |
| Database | SQLite (local) / Aurora PostgreSQL Serverless v2 (AWS) | One portable SQL layer (`app/db.py`); JSON stored as TEXT |
| Raw + documents | Local disk / S3 | `BlobStore` interface |
| Search | In-process BM25 (default) / OpenSearch (optional) | `SearchIndex` interface; both derived from the HSDS store |
| LLM | Mock rules (local) / Amazon Bedrock Converse (AWS) | `LLM` interface; callers have a deterministic path for the mock |
| Auth | Local scrypt + HS256 JWT / Amazon Cognito | `AuthProvider` interface; roles seeker, provider, admin |
| Jobs | Thread (local) / ECS Fargate RunTask via EventBridge Scheduler | Same image, `python -m app.jobs.run` |
| UI | Vanilla JS single-page app, no build step | Served by the Flask container; can move to S3 + CloudFront |
| IaC / CI | Terraform / GitHub Actions (OIDC) | `infra/terraform`, `.github/workflows` |

## 2. HSDS handling
- Pinned version 3.2.3, schema directory `schemas/hsds/<version>` (configurable). Validator uses `jsonschema` (Draft 2020-12) when installed, otherwise a built-in subset validator.
- **The vendored schemas are a hand-authored subset.** `scripts/fetch_hsds_schemas.py` replaces them with the official files. Until then conformance is conformance to the subset.
- Boundary rule: everything served is HSDS JSON. Extensions live in one property, `x_resource_engine` (source info, flags, last_check); hidden unless `?extensions=true`.
- IDs are UUIDv5 from source + kind + native id, so re-ingest is idempotent. Empty properties are omitted. Schedules use RFC 5545 weekly rules with offset times plus `timezone`.
- Taxonomies are per source (`One Degree`, `One Degree Eligibility`, `211 NDP Taxonomy`), linked to services by `attribute` records.

## 3. Data model (summary)
`resource` holds one HSDS JSON document per organization, service, location, service_at_location, taxonomy and taxonomy_term (children such as phones and schedules are embedded and carry their own ids). Workflow tables: `raw_payload`, `import_run`, `quarantine`, `resource_source` (source snapshot for reconciliation), `change_history` (HSDS metadata shape), `change_request`, `check_result`, `maintenance_run`, `users`, `seeker_profile`, `help_request`, `chat_session`, `chat_message`, `document`, `doc_chunk`, `api_key`. Rationale in ADR-2: storing HSDS as documents keeps HSDS version changes cheap, while the relational tables handle workflow, joins and integrity.

## 4. Key algorithms
**Ingest** (`app/services/ingest.py`): fetch pages, store raw bytes, map each source record to HSDS, validate every resulting object, then upsert all objects for that record in one transaction; any failure quarantines the whole record. First version of a shared resource (organization, location, term) wins within a run; disagreements are counted.
**Reconciliation**: per top-level field, compare *new source value*, *last source snapshot* and *current value*. Source unchanged: keep current. Only source changed: apply (history actor `source`). Both changed differently: keep current, open a `conflict` change request.
**Maintenance** (`app/services/maintenance.py`): fetch the organization website (cached per run, skipped when page hash and record version are unchanged), extract facts with evidence snippets, compare facts only, assign a category with priority actively_bad > check_failed > discrepancy > missing_information > verified, and create `ai_finding` change requests. Findings without evidence are dropped.
**Chat** (`app/services/chat.py`): crisis → about → policy → service-need → clarify. Service need without a profile returns signup/login actions and no provider data. Requests require a confirm action and sharing consent.
**Search**: BM25 over weighted fields (name, taxonomy path, organization, description, eligibility), plain-language query expansion (`diapers` → baby, infant, household, supplies), optional proximity boost from ZIP centroids.

## 5. API surface
App API `/api/*` (JWT; see `app/web/routes_app.py`) and HSDS API `/hsds/*` (API key): `GET /`, `/services` (page, per_page, modified_after, organization_id, taxonomy_term_id, taxonomy_id, minimal, search), `/services/{id}`, `/organizations[/{id}]`, `/service_at_locations[/{id}]`, `/locations[/{id}]`, `/taxonomies`, `/taxonomy_terms[/{id}]`. Lists use the HSDS Page object. POST endpoints are not implemented.

## 6. Non-functional requirements
Security: keys hashed (SHA-256), passwords scrypt, least-privilege IAM, encryption at rest and in transit, private DB subnets, S3 public access blocked, provider access enforced server-side by organization. Observability: CloudWatch logs; import and maintenance run tables; `/api/health`. Cost: no NAT, Aurora scales to 0.5 ACU, scheduled jobs are one-off Fargate tasks, in-process search by default, page-hash skipping avoids repeat model calls.

## 7. Extensibility
New source: subclass `SourceAdapter` (`parse_page`, `native_id`, `map`, optional `fetch_http`), register in `app/adapters/registry.py`, add an entry to `config/sources.json`. New HSDS version: point `HSDS_SCHEMA_DIR` at the new files and re-run tests; fields live in JSON so no table migration. New LLM, search or blob backend: implement the interface and select it in `app/container.py`.
