# Deploying to AWS

Source repository: `alina-cheng/resource_engine`. Use only this repository's root as the build context. Do not publish sibling `local_refs` or the original engine. Local development, CI and Docker install the committed uv.lock.

Start with the [README deployment guide](../README.md#deploy-to-aws) for the scripted path, source configuration and initialization order. The [project status](../README.md#project-status) records the last observed cloud state; local validation and functional cloud verification are separate. For the OneDegree event, first follow [Workshop Studio login](workshop-aws.md); use the workshop profile, us-west-2, the $500 account cap and the organizer's service/security rules.

## One-time OIDC/state bootstrap

`infra/bootstrap` provisions an encrypted/versioned/private Terraform state bucket and a deploy role trusting only `repo:alina-cheng/resource_engine:environment:production` via GitHub OIDC. It reuses an existing OIDC provider by default; set create_github_oidc=true only when the account has none and creation is permitted. Bootstrap state is local and ignored by Git; preserve it securely outside an expiring account.

```bash
export AWS_PROFILE=workshop
export AWS_REGION=us-west-2
aws sts get-caller-identity
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap plan -out=bootstrap.tfplan -var=create_github_oidc=true
# Inspect the plan and actual IAM permissions before applying.
terraform -chdir=infra/bootstrap apply bootstrap.tfplan
terraform -chdir=infra/bootstrap output
```

Configure GitHub secret `AWS_DEPLOY_ROLE_ARN` from deploy_role_arn, variables `TF_STATE_BUCKET`, `AWS_REGION`, `BEDROCK_MODEL_ID`, and an Environment named production. Restrict deployment branches/reviewers through the repository administrator. If workshop IAM denies OIDC/role creation, record the denied action and use authorized operator-run temporary credentials for this event; do not attempt to change organizer guardrails.

The bootstrap deployment policy is a sandbox starting point covering this stack, with project-prefixed IAM role/pass-role access. Review/tighten service scopes for a durable account. It does not grant the participant a way around organization/session guardrails.

## Account and source configuration

- Confirm Aurora PostgreSQL engine/version availability, Fargate capacity, and an accessible Bedrock model/inference profile in us-west-2. `bedrock_model_id` deliberately has no default; task planning rejects Bedrock without a configured model.
- Copy infra/terraform/workshop.tfvars.example to workshop.tfvars (ignored), fill the actual model and supplied HTTPS mocked/live ODRS/NDP URLs. Those endpoints use the existing adapters and preserve raw responses.
- Source credentials stay in existing Secrets Manager secrets. Map `ODRS_API_KEY` for the configured ODRS API, or the configured bearer environment name for a bearer-authenticated feed, through `source_token_secret_arns`; values never enter Terraform variables/state. ECS execution-role access is extended to those ARNs.
- Outside local mode source globs are disabled unless explicitly allowed for synthetic demonstrations. Do not describe generated samples or mocked APIs as a live One Degree feed.
- For a persistent synthetic workshop demo, set `sources_config = "/srv/config/sources.demo.json"` and `allow_sample_sources = true` in the ignored environment tfvars. Terraform injects both settings into the shared web/job task definition, so admin uploads, imports and later jobs use the same source configuration. Leave the override false for live feeds. This does not re-import or reset existing records.
- The repository now defaults to the configured ODRS HTTPS API (one page of 25) and local NDP sample files. The NDP file glob still requires a hosted HTTPS feed or an explicit synthetic-demo override on AWS. `config/sources.demo.json` selects generated files for local demos. JSON upload is available in the admin Imports page; it uses the same schema/quarantine pipeline.
- `schedules_enabled` defaults false; enable only after source/model validation. `workshop_mode=true` permits RDS teardown without a final snapshot/deletion protection; durable production defaults retain protection.
- `maintenance_schedule_enabled=true` enables only the daily maintenance schedule, without also scheduling imports. `auto_maintenance_after_import=true` queues an all-backlog check after nonempty configured imports or JSON uploads. Manual checks drain the backlog instead of inheriting the periodic daily budget; the overview offers an explicit all-record check and checked/target progress. Sample evidence can use `maintenance_concurrency=2`; live fetching remains serial.
- Set certificate_arn for ACM HTTPS before sending login credentials through the public load balancer. Domain/certificate ownership and DNS are not created automatically.

## Build and deploy

```bash
terraform -chdir=infra/terraform init -backend-config="bucket=<state-bucket>" -backend-config="key=resource-engine.tfstate" -backend-config="region=us-west-2"
terraform -chdir=infra/terraform apply -target=aws_ecr_repository.app -var-file=workshop.tfvars -var=image_tag=bootstrap
```

Log Docker into ECR with aws ecr get-login-password; the password goes directly to docker login --password-stdin and must never be logged. Build/tag/push from this repo. On Apple Silicon select `docker buildx build --platform linux/amd64` because the ECS task defaults to X86_64; alternatively explicitly configure a matching ARM64 runtime platform. Tag the image with the exact source commit SHA. Then plan with that tag and inspect changes before apply:

```bash
terraform -chdir=infra/terraform plan -var-file=workshop.tfvars -var="image_tag=<commit-sha>" -out=deployment.tfplan
terraform -chdir=infra/terraform apply deployment.tfplan
```

The GitHub deploy workflow runs tests, assumes the OIDC role, bootstraps ECR, builds/pushes the image, applies Terraform and checks service health. Repository variables must supply the chosen model/source settings before an automated production deployment.

## End-to-end validation

1. Check /api/health shows postgres, expected auth/blob/model backends and the official HSDS validator. This endpoint reports composition, so also perform actual reads/writes.
2. Run a small import through a one-off ECS task (`python -m app.jobs.run import`) or through the admin UI after creating an administrator. Every enabled source needs a configured HTTPS endpoint. For generated-file demonstrations, explicitly add `ALLOW_SAMPLE_SOURCES=true` to the one-off container environment; this does not change subsequent web/scheduled tasks. Inspect source-record/object balance, partial sources, held objects and preserved raw bytes. Verify stored and nested API data against official schemas.
3. For synthetic data containing the demo organizations, run `make demo-accounts` locally to create the login page accounts (admin@demo.org, provider1@demo.org, ana@demo.org) with permanent passwords. The provider requires the imported Bay Area Diaper Bank organization. Set `APP_URL` to the application's HTTPS URL. Alternatively, `python -m app.jobs.run seed-demo --limit 5` as a one-off ECS task adds demo logins, requests, reports and policy documents. It creates no API keys outside local mode; a real-model maintenance pass requires an explicit limit. Use the same source configuration/overrides as the import task if the store is empty. Demo credentials are public: keep this path on synthetic data and disable the accounts when the demo ends. For a private admin instead, use admin-create-user with Name=email_verified,Value=true, then admin-add-user-to-group before the first login. Check all three personas and provider-to-organization links.
4. Run a limited maintenance check with real Bedrock. A quote-grounded proposal must stay pending until an admin approves; check resulting resource version and actor/approver history.
5. Start jobs through the admin UI and verify a job ID/task ARN/status. CLI executes persisted parameters; ECS launch failures and application errors must end in failed status, not a false “started” result.
6. Verify S3 document/raw readback, reconnect/restart persistence, and an HSDS API key. Keep OpenSearch disabled until its remaining limitations are resolved.

## Operate and preserve

Logs: /ecs/resource-engine; status/history: admin console and database job/run tables. EventBridge uses UTC cron expressions; fixed UTC times do not equal one Pacific wall-clock time all year. Aurora backups and S3 versioning reside inside the account, so a workshop cleanup can remove them as well. Export required demo data, source/lock files and deployment evidence outside the event account before it ends. Never commit database dumps or Terraform state/plans.

Secrets injected into ECS are read when a task starts. Rotation requires a new task/deployment to refresh the environment ([AWS documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html)). Confirm model activation/access using the current [Bedrock account requirements](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html).
