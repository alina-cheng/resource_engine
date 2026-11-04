# One Degree Resource Engine

Ingests community-resource data (One Degree ODRS and 211 NDP formats), converts it to Open Referral **HSDS 3.2.3**, keeps it accurate with an **AI maintenance worker** that humans supervise, and serves **help seekers**, **providers** and **One Degree admins**. Runs on AWS (ECS Fargate, Aurora, Bedrock, Cognito, S3) and locally with no cloud account.

## Try it (2 minutes)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
make demo            # http://127.0.0.1:8000
```
Or `docker compose up --build`. Demo accounts and a guided tour: [docs/local-run.md](docs/local-run.md).

## What is in here
| Path | Contents |
|---|---|
| `app/` | adapters, HSDS validation and nesting, services (ingest, store, approvals, maintenance, chat, search, documents), Flask routes, jobs |
| `frontend/` | no-build single-page app for the three personas |
| `tools/sample_data_generator/` | demo data generator and seeder built from your sample files |
| `tests/` | 40 tests, including a seeded evaluation of the AI maintenance worker |
| `infra/terraform/`, `.github/workflows/` | AWS infrastructure and CI/CD |
| `docs/` | BRD, technical spec, detailed design (Mermaid diagrams), HSDS mapping, deployment, local run, test plan, decisions, known limitations |
| `.kiro/` | steering files and specs (requirements, design, tasks) per feature; task checkboxes show what is done |

## Status: read this first
Tested locally: ingest, HSDS mapping and validation, approvals, history, HSDS API, chat, matching, documents, maintenance (40 tests, plus a browser walk-through of all three personas).
**Not tested here:** PostgreSQL, Cognito, S3, Bedrock, OpenSearch, Textract, live website fetching, Terraform apply. HSDS validation uses the official v3.2.3 schemas in `schemas/hsds/3.2.3/`. **Personal data** needs a privacy review. Full list: [docs/known-limitations.md](docs/known-limitations.md).
