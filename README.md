# One Degree Resource Engine

**Keeps community resource listings accurate, with AI that proposes updates and people who approve them.**

![HSDS 3.2.3](https://img.shields.io/badge/HSDS-3.2.3-1E3A8A) ![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB) ![Runs on AWS](https://img.shields.io/badge/Runs%20on-AWS-F97316) ![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC)

[Features](#features) · [Architecture](#architecture) · [Quick start](#quick-start) · [Deploy](#deploy-to-aws) · [Verify](#verify-a-deployment) · [Status](#project-status) · [Docs](#documentation)

---

## Why this exists

[One Degree](https://www.1degree.org) helps low-income families find free and low-cost services. Its directory lists more than 30,000 resources, and those listings start going out of date the day they are published. Today, staff and volunteers check them by hand.

The Resource Engine moves legacy data into one open standard, checks records against organization websites, and gives reviewers a short list of proposed fixes with the evidence attached.

## Features

| Who | What they can do |
|---|---|
| **Help seekers** | Ask questions, search for services, and choose what to share when requesting help |
| **Providers** | Propose updates to their listings and respond to requests from people who consent to share |
| **One Degree admins** | Review evidence, approve or reject changes, run imports and AI checks, and manage API keys |
| **Data partners** | Read validated data through an HSDS API, with keys that can be limited to one source |

## Architecture

![One Degree Resource Engine AWS architecture](docs/AWS%20Resource%20Engine%20Architecture%20Diagram.png)

One container image runs the Flask web app and the one-off import and maintenance jobs on ECS Fargate.

### How data moves

**Import**

1. Save the source data exactly as received.
2. Map it to HSDS and validate it against the official 3.2.3 schemas.
3. Store valid objects. Quarantine invalid objects and their dependents with a reason.
4. On re-import, keep IDs stable, apply source-only changes, and send clashes with human edits to an admin.

**AI maintenance**

1. Select records that are due or were reported by users.
2. Read the organization's website, using sample pages or live sites.
3. Extract facts, keeping only those whose quote appears on the page.
4. Compare the facts with the record and create a proposal with evidence.
5. An admin approves or rejects it. AI cannot publish changes, and applied changes are recorded in the audit history.

### Technology

| Layer | Technology |
|---|---|
| Frontend | Vanilla JavaScript, HTML, and CSS, with no build step |
| Backend | Python 3.12, Flask, Gunicorn |
| Database | Amazon Aurora PostgreSQL Serverless v2 |
| File storage | Amazon S3 |
| AI | Amazon Bedrock |
| Search | In-process BM25; OpenSearch is optional and needs further validation |
| Data standard | Open Referral HSDS 3.2.3 |
| Hosting | Amazon ECS Fargate, Application Load Balancer, Amazon ECR |
| Identity and secrets | Amazon Cognito, AWS Secrets Manager, hashed API keys |
| Operations | Amazon CloudWatch Logs; Amazon EventBridge Scheduler is optional |
| Delivery | Docker, Terraform, GitHub Actions, uv |

<details>
<summary><b>Local and AWS backends</b></summary>

Backends are selected in `app/container.py`.

| Concern | Local default | AWS deployment |
|---|---|---|
| Database | SQLite | Aurora PostgreSQL Serverless v2 in private subnets |
| Authentication | Local accounts | Cognito |
| Raw payloads and documents | Local disk | S3 |
| Language model | Mock/rules | Bedrock, or explicit mock mode |
| Website evidence | Generated sample pages | Configurable `sample` or `live` |
| Search | In-process BM25 | BM25 by default; optional OpenSearch |
| Jobs | Local threads or CLI | One-off Fargate tasks; optional EventBridge schedules |

</details>

## Quick start

You need **Python 3.12+**, **uv**, and **Make**. No AWS account or model key is required.

```bash
uv sync --frozen
make demo
```

Open **http://127.0.0.1:8000** and sign in with a demo account:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@demo.org` | `demo-admin-1` |
| Provider | `provider1@demo.org` | `demo-provider-1` |
| Help seeker | `ana@demo.org` | `demo-seeker-1` |

The demo uses `config/sources.demo.json`, stores its data in `var/demo`, and runs mock maintenance on synthetic data. Existing databases are preserved. See the [local run guide](docs/local-run.md) for a guided tour.

<details>
<summary><b>Run with Docker</b></summary>

```bash
docker compose up --build                      # SQLite: http://localhost:8000
docker compose --profile pg up --build app-pg  # PostgreSQL 16: http://localhost:8001
```

</details>

<details>
<summary><b>Import configured sources</b></summary>

`config/sources.json` uses the ODRS HTTPS API with `ODRS_API_KEY` and the two local NDP sample files. ODRS is capped at one page of 25 records by default. Use an authorized event or staging key. `.env` loads without overriding existing environment variables.

```bash
uv run --frozen python -m app.jobs.run import
```

- `seed-demo --no-maintenance` skips checks, and real-model seeding otherwise requires an explicit `--limit`.
- Admins can upload source-format JSON on the Imports page. It uses the same validation and quarantine pipeline, but does not add spreadsheet ingestion.
- The [API console](frontend/console.html) is served at `/console.html`, and the [API report](reports/API_REPORT.md) documents the verification harness.

</details>

### Synthetic data, real data, and HSDS

**HSDS is the exchange format, not a statement about where a record came from.** The current AWS demo contains 300 synthetic services stored and served as HSDS 3.2.3. Its website evidence comes from generated sample pages, while fact extraction uses the real Claude Sonnet 4.6 model on Amazon Bedrock. A separate validation database accepted 50 supplied public ODRS records and exercised two real-website model calls; those records have not replaced the cloud demo corpus.

For an authorized event/staging API with the supported ODRS or NDP response shape, reuse the existing adapters and pipeline:

1. Select `/srv/config/sources.json` through `sources_config`, set `allow_sample_sources=false`, and supply the HTTPS ODRS/NDP endpoints. Each enabled source needs an HTTPS location; disable a source that is not connected yet.
2. Store the ODRS API key or configured bearer token in Secrets Manager and inject its environment name through `source_token_secret_arns`. Keep credential values out of source control and chat.
3. Review adapter options with the endpoint: ODRS has a separate `organizations_url` lookup and a one-page/25-record demo cap; NDP bearer authentication requires a configured `bearer_env`. Confirm pagination and field mappings against a small authorized response before increasing volume.
4. Use an isolated validation environment or an explicit migration plan when replacing synthetic records. Validate HSDS, raw preservation, count balance, repeated imports and conflicts before publishing the new dataset.
5. Real website maintenance also needs the live website backend and its documented fetch/scoping hardening. Enabling Claude alone does not switch the evidence source from samples to live pages.

If an API uses a different structure, including a direct HSDS feed, add or adjust one adapter rather than rewriting storage, the API or the frontend. The current registry contains ODRS and NDP adapters; neither an arbitrary real API nor every HSDS API shape is automatically compatible.

## Deploy to AWS

**Before you start:** install Git, AWS CLI, Docker with Buildx, Terraform **1.10+**, Make, Python, and uv. Start the Docker engine. Your AWS identity must be able to provision the stack and pass its ECS roles.

### 1. Set credentials

For another account, use its authorized profile. For the workshop account, get temporary CLI credentials from the event dashboard, then run:

```bash
uv sync --frozen
uv run --frozen python scripts/configure_workshop_profile.py
export AWS_PROFILE=workshop
export AWS_REGION=us-west-2
aws sts get-caller-identity
```

The helper stores workshop credentials in your user AWS configuration, outside the repository. See [workshop access and account lifetime](docs/workshop-aws.md).

### 2. Configure the environment

```bash
cp -n infra/terraform/workshop.tfvars.example infra/terraform/workshop.tfvars
```

Edit `infra/terraform/workshop.tfvars`, replacing the placeholders:

```hcl
region            = "us-west-2"
workshop_mode     = true
schedules_enabled = false
db_engine_version = "16.15"

llm_backend      = "bedrock"
bedrock_model_id = "REPLACE_WITH_ACCOUNT_ENABLED_MODEL_OR_INFERENCE_PROFILE"
website_backend  = "sample"

# Authorized live feeds or hosted HTTPS synthetic feeds; replace both examples.
odrs_api_url = "https://your-odrs-feed.example/resources"
ndp_api_url  = "https://your-ndp-feed.example/resources"

# Issued ACM certificate for your domain; required before public login.
# certificate_arn = "arn:aws:acm:us-west-2:ACCOUNT_ID:certificate/CERTIFICATE_ID"

# Existing Secrets Manager ARNs, never source credential values.
# source_token_secret_arns = { ODRS_API_KEY = "arn:aws:secretsmanager:..." }
```

Confirm that the database engine and model are available in the account. For a demo without model calls, set `llm_backend = "mock"` and `bedrock_model_id = ""`.

<details>
<summary><b>What these settings affect</b></summary>

- **Imports:** every enabled source in `config/sources.json` needs an HTTPS endpoint on AWS. Disable sources you have not connected. Empty endpoints leave local file paths, which AWS import rejects.
- **Website mode:** `sample` reads generated website evidence, and `live` fetches real sites. This does not configure ODRS or NDP feeds.
- **Scheduling:** keep `schedules_enabled = false` until manual import and maintenance succeed.
- **Account lifetime:** `workshop_mode = true` permits database deletion without a final snapshot. Use `false` for durable environments and review backup and recovery requirements.
- **HTTPS:** `certificate_arn` enables HTTPS and HTTP redirect. Manage the domain and its ALB DNS mapping separately.

</details>

### 3. Build and apply

Commit your changes first, so the image tag identifies the build:

```bash
git status --short
make deploy
```

The script checks your AWS identity and asks for confirmation twice:

1. **Bootstrap:** create or reuse the private, versioned state bucket and ECR repository, then build and push a `linux/amd64` image tagged with the short commit SHA. The first confirmation already permits these changes.
2. **Apply:** show the Terraform plan and ask before applying the rest of the stack.

It then waits for ECS to stabilize and checks `/api/health`. Get resource identifiers with:

```bash
terraform -chdir=infra/terraform output
```

<details>
<summary><b>Deployment options</b></summary>

- `TFVARS=/absolute/path/to/environment.tfvars make deploy` selects another settings file.
- `DEPLOY_ALLOW_DIRTY=1 make deploy` allows an intentional uncommitted build. Its timestamped tag requires a separate source record.
- State uses bucket `resource-engine-tfstate-<account>-<region>` and key `resource-engine.tfstate`. Reuse that backend for updates.

</details>

### 4. Load data and create accounts

Creating infrastructure does not add data. Import through the admin console after creating an administrator, or start a one-off task from **ECS → resource-engine cluster → Tasks → Run new task**. Select the deployed task definition, the service's subnets and security group, and an enabled public IP. Then override the `app` container command:

```text
python -m app.jobs.run import
```

For another dataset, create a private admin and provider logins linked to the actual organizations. See [end-to-end validation](docs/deployment.md#end-to-end-validation).

<details>
<summary><b>Set up a synthetic demo</b></summary>

After importing the synthetic `Bay Area Diaper Bank` organization, create or reset the three login-page accounts:

```bash
APP_URL=https://your-domain.example make demo-accounts
```

If that organization is missing, the script creates the admin and seeker accounts, then reports the missing provider association.

To seed demo profiles, requests, reports, and policy documents, run another one-off ECS task:

```text
python -m app.jobs.run seed-demo --limit 5
```

- Seeding imports sources if the service store is empty, creates Cognito demo logins without invitation emails, and preserves existing application data on repeat runs.
- The limit bounds this seed's real-model maintenance pass.
- Outside local mode, create API keys in the admin console so their values do not appear in seed logs.
- For a persistent synthetic demo, set `sources_config = "/srv/config/sources.demo.json"` and `allow_sample_sources = true` in the environment tfvars. Terraform applies them consistently to web and jobs. A one-off container override affects only that task; a local shell export does not reach ECS.
- `maintenance_schedule_enabled=true` enables daily maintenance separately from imports. `auto_maintenance_after_import=true` queues checks after nonempty imports/uploads. Manual checks drain the backlog, and the overview provides a full-corpus action with checked/target progress; the daily recheck budget does not limit that initial pass.
- Demo credentials are public and intended only for synthetic data. Use the application's HTTPS URL for account operations, because the script otherwise defaults to the HTTP ALB address.

</details>

### 5. Update a deployment

Commit your changes, refresh temporary credentials if needed, and run `make deploy` with the same account, region, and backend. Review the plan and repeat the [verification checks](#verify-a-deployment).

> **Note:** A Git push or a healthy existing task does not confirm that the new image is running.

<details>
<summary><b>Deploy with GitHub Actions</b></summary>

The [deploy workflow](.github/workflows/deploy.yml) provides a separate OIDC path. Follow the [OIDC and state bootstrap](docs/deployment.md#one-time-oidcstate-bootstrap), then configure:

| GitHub setting | Purpose |
|---|---|
| Environment `production` | Deployment environment and optional reviewer or branch rules |
| Secret `AWS_DEPLOY_ROLE_ARN` | Authorized OIDC deploy role |
| Variables `TF_STATE_BUCKET`, `AWS_REGION` | Existing state backend and region |
| Variables `BEDROCK_MODEL_ID`, `ODRS_API_URL`, `NDP_API_URL` | Model and HTTPS sources |
| Optional variables `WORKSHOP_MODE`, `SCHEDULES_ENABLED`, `SOURCE_TOKEN_SECRET_ARNS` | Lifetime, scheduling, and source-token ARN mapping |
| Variable `AWS_DEPLOY_ENABLED=true` | Automatic deployment on pushes to `main` |

- Manual `workflow_dispatch` also deploys after its test job. Pushes to `deploy` do not deploy automatically.
- The workflow does not read your ignored local `workshop.tfvars`. Add workflow configuration for overrides such as `website_backend` and `certificate_arn` before switching delivery paths.
- Reuse the stack's state bucket and key, and keep workshop temporary credentials out of GitHub secrets.

</details>

## Verify a deployment

```bash
curl --fail --silent --show-error https://your-domain.example/api/health
```

Expect `status=ok`, `database=postgres`, `auth=cognito`, `blob=s3`, and the official HSDS 3.2.3 validator. Health reports configuration only, so also check actual behavior:

- [ ] **Access:** log in as admin, provider, and seeker. Check provider organization links and access boundaries.
- [ ] **Import:** import a small dataset twice. Check idempotence, source and object counts, partial imports, quarantine reasons, and raw S3 readback.
- [ ] **AI:** run limited maintenance. Confirm a real Bedrock response and an evidence-backed proposal, then approve it and inspect its version and history. Chat can fall back to a preset answer, so a reply alone is not proof.
- [ ] **Jobs:** start an admin job and verify its job ID, ECS task ARN, and final status. Check `/ecs/resource-engine` CloudWatch logs for failures.
- [ ] **Documents and API:** upload and approve a document, check its cited answer, create and revoke an HSDS API key, and confirm data survives task replacement.
- [ ] **Schedules:** enable them only after these checks, then confirm an actual run. Cron expressions use UTC.

## Project status

This is a workshop demo using synthetic data, not a production service.

**Last observed deployment, 2026-11-04 (America/Los_Angeles)**

| Area | Observed state |
|---|---|
| Hosting | AWS `us-west-2`; one running ECS task |
| Health | `ok` with PostgreSQL, Cognito, S3, and the official HSDS 3.2.3 validator |
| AI | Full 300-service maintenance pass completed using Bedrock profile `us.anthropic.claude-sonnet-4-6` for readable-page extraction |
| Data | 300 synthetic services in HSDS 3.2.3; sample website evidence; Imports page working; no live ODRS/NDP feeds connected |
| Coverage | 300/300 checked, 0 unchecked: 20 actively bad, 13 check failed, 27 discrepancy, 28 missing information, 212 verified; 57 pending AI proposals |
| Search and scheduling | In-memory search; daily maintenance enabled at 12:00 UTC; import-triggered checks enabled |
| Transport | HTTP only; configure HTTPS before public login |
| Image | `46003ef`, task definition `resource-engine:3`, ECS rollout completed; later documentation-only commits do not change the running application |

**Known gaps**

- **Maintenance:** changed hours and accessibility are flagged only when the record lacks those fields. The full real-model review hash is now persisted; field coverage and multi-program scoping still need improvement. Pages without comparable evidence are check_failed rather than verified.
- **Accuracy:** seeded thresholds use synthetic pages. The separate two-page real-website check establishes integration, not accuracy on real websites.
- **Before production:** fix chat-session ownership, provider request claiming, and consent withdrawal. Add HTTPS, account recovery, rate limiting, real-page evaluation, task recovery, and monitoring.
- **Not implemented:** spreadsheet ingestion, source-deletion handling, cross-source deduplication, semantic or multilingual search, and HSDS write endpoints.
- **OpenSearch:** filters and shared-index rebuild behavior need repair before it is enabled.

See [known limitations](docs/known-limitations.md) for details.

## Development

```bash
make test
terraform -chdir=infra/terraform validate
```

The last full local run had **114 tests passing, with 4 PostgreSQL integration tests skipped**. The coverage suite subsequently passed all **7** cases including the added concurrency case, and the **4 PostgreSQL integration tests passed separately**. To include PostgreSQL checks, set `TEST_DATABASE_URL` to a **disposable local PostgreSQL database**. CI provisions PostgreSQL automatically.

For a fresh validation-only checkout, first run `terraform -chdir=infra/terraform init -backend=false`. Keep it separate from a checkout configured for deployment.

Keep credentials, databases, Terraform state and plans, `.tfvars`, and workshop exports out of Git. Save required data and deployment evidence outside an expiring account before cleanup.

### Repository map

| Path | Contents |
|---|---|
| `app/` | API, adapters, HSDS validation, services, maintenance, and job CLI |
| `frontend/` | JavaScript UI for all three roles, served by Flask, plus the API console |
| `schemas/hsds/3.2.3/` | Pinned official schemas |
| `config/`, `content/` | Source definitions and about and policy content |
| `tools/sample_data_generator/` | Synthetic data, website fixtures, and demo seeding |
| `tests/`, `reports/` | Regression, maintenance evaluation, PostgreSQL checks, and API verification |
| `scripts/` | Deployment, demo accounts, credentials, and schema tools |
| `infra/`, `.github/workflows/` | AWS stack, state and OIDC bootstrap, and CI/CD |
| `.kiro/` | Steering and feature requirements, design, and tasks |
| `docs/` | Product, architecture, mapping, and operations details |

## Documentation

| Topic | Documents |
|---|---|
| **Product** | [Business requirements](docs/BRD.md) · [Decisions](docs/decisions.md) · [Known limitations](docs/known-limitations.md) |
| **Design** | [Technical specification](docs/technical-spec.md) · [Detailed design](docs/detailed-design.md) · [HSDS mapping](docs/hsds-mapping.md) |
| **Running it** | [Local run](docs/local-run.md) · [Deployment details](docs/deployment.md) · [Workshop AWS access](docs/workshop-aws.md) |
| **Quality** | [Test plan](docs/test-plan.md) · [API report](reports/API_REPORT.md) · [Kiro and prompt audit](docs/kiro-and-prompts-audit.md) |
