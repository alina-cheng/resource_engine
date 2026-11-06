# Tech
- Python 3.12, Flask, gunicorn. SQLite locally, Aurora PostgreSQL on AWS, one portable SQL layer in `app/db.py` (`?` placeholders, text ids, JSON as TEXT).
- HSDS pinned to 3.2.3; official schemas in `schemas/hsds/3.2.3`, restored from the original engine. Original core transforms and IDs live in `app/adapters/transform`; FINAL enrichment must pass the same validator. Extensions only under `x_resource_engine`; IANA schedule context is not the numeric HSDS timezone property.
- Dependency source: `pyproject.toml` + `uv.lock`; use `uv sync --frozen` and `uv run`. Update the lock with dependency changes.
- Backends sit behind interfaces chosen in `app/container.py`: LLM (mock|bedrock), search (memory|opensearch), blob (local|s3), auth (local|cognito), website (sample|live).
- Tests: `make test` (stdlib unittest). Every behaviour change needs a test; maintenance changes must keep the seeded evaluation thresholds.
- Never write HTML from data with innerHTML; the UI builds DOM with `h()`.
- Infra: Terraform in `infra/terraform`, GitHub Actions in `.github/workflows`. Cost control: no NAT, serverless database, scheduled jobs as one-off Fargate tasks.
- Keep specs, task evidence and docs synchronized with changes. See `docs/kiro-and-prompts-audit.md`; runtime prompts are inventoried there. For expiring event accounts follow `docs/workshop-aws.md`, separately from persistent production OIDC deployment.
