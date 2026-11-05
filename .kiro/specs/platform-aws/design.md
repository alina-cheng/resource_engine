# Design: AWS platform and delivery

- `infra/terraform/*.tf`; `.github/workflows/ci.yml`, `deploy.yml`; `Dockerfile`, `docker-compose.yml`, `Makefile`.
- `docs/deployment.md`.
- Expiring AWS Workshop Studio account: login, temporary CLI profile, regional restrictions and export/redeployment requirements are documented in `docs/workshop-aws.md`. Production OIDC remains a separate delivery path; temporary event credentials are not a durable GitHub secret.
- Integration status and prompt/spec synchronization: `docs/kiro-and-prompts-audit.md`. Do not mark Terraform apply or real service calls complete before execution evidence exists.
- `infra/bootstrap`: encrypted/versioned state bucket and repository/environment-scoped GitHub OIDC role. Apply requires authorized AWS credentials and the event's IAM permissions; existing OIDC provider is reused by default.
- `job_run` stores params/results/failures/task ARN. ECS command transports only kind/job ID; CLI reads persisted params, so booleans never become invalid --force=True arguments. Admin UI polls `/api/admin/jobs/{id}`. Local CLI executes directly without recursively launching ECS.
- Cognito login returns signed expiring first-password/MFA challenges; `/api/auth/challenge` and the login dialog complete them. Verify token issuer/audience/token_use/email_verified; admin-created staff use the requested group.
- `workshop_mode` explicitly disables RDS deletion protection/final snapshot on teardown; production defaults retain protection. Schedules stay disabled until data endpoints/model validation are ready. Secrets Manager source token ARNs are injected into task definitions; real source endpoints are variables. Model ID has no guessed default.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
