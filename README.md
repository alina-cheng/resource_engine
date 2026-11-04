# One Degree Resource Engine

Ingests community-resource data (One Degree ODRS and 211 NDP formats), converts it to Open Referral **HSDS 3.2.3**, keeps it accurate with an **AI maintenance worker** that humans supervise, and serves **help seekers**, **providers** and **One Degree admins**. Runs on AWS (ECS Fargate, Aurora, Bedrock, Cognito, S3) and locally with no cloud account.

## Try it (2 minutes)
```bash
uv sync --frozen
make demo            # http://127.0.0.1:8000
```
Or `docker compose up --build`. Demo accounts and a guided tour: [docs/local-run.md](docs/local-run.md).

## What is in here
| Path | Contents |
|---|---|
| `app/` | adapters, HSDS validation and nesting, services (ingest, store, approvals, maintenance, chat, search, documents), Flask routes, jobs |
| `frontend/` | no-build single-page app for the three personas |
| `tools/sample_data_generator/` | demo data generator and seeder built from your sample files |
| `tests/` | Python regression and real PostgreSQL integration tests, including seeded maintenance evaluation |
| `infra/terraform/`, `.github/workflows/` | AWS infrastructure and CI/CD |
| `docs/` | BRD, technical spec, detailed design (Mermaid diagrams), HSDS mapping, deployment, local run, test plan, decisions, known limitations |
| `.kiro/` | steering files and specs (requirements, design, tasks) per feature; task checkboxes show what is done |

## Status: read this first
Official HSDS 3.2.3 schemas and the original engine's core source transforms and transaction protections are included. Invalid HSDS objects and dependent children are quarantined; valid independent data is imported atomically. Admin imports show partial-source and held-object counts.

Integration check on 2026-11-04: **74 Python tests passed against SQLite and PostgreSQL 16**. Docker image build and main Terraform validation passed. Cloud Cognito, S3, Bedrock, OpenSearch, Textract, live source endpoints and Terraform apply remain unverified. See [deployment](docs/deployment.md), [Workshop Studio access](docs/workshop-aws.md), [Kiro/prompt audit](docs/kiro-and-prompts-audit.md) and [limitations](docs/known-limitations.md). Runtime secrets and local data are never committed.
