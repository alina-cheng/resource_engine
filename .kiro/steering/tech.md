# Tech
- Python 3.12, Flask, gunicorn. SQLite locally, Aurora PostgreSQL on AWS, one portable SQL layer in `app/db.py` (`?` placeholders, text ids, JSON as TEXT).
- HSDS pinned to 3.2.3; schemas in `schemas/hsds/3.2.3` (currently a vendored subset: replace with official files). Everything served is valid HSDS JSON; extensions only under `x_resource_engine`.
- Backends sit behind interfaces chosen in `app/container.py`: LLM (mock|bedrock), search (memory|opensearch), blob (local|s3), auth (local|cognito), website (sample|live).
- Tests: `make test` (stdlib unittest). Every behaviour change needs a test; maintenance changes must keep the seeded evaluation thresholds.
- Never write HTML from data with innerHTML; the UI builds DOM with `h()`.
- Infra: Terraform in `infra/terraform`, GitHub Actions in `.github/workflows`. Cost control: no NAT, serverless database, scheduled jobs as one-off Fargate tasks.
