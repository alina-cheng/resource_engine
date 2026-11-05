# Kiro specifications and prompts: integration audit

Reviewed 2026-11-04 before continuing the AWS-readiness integration. Scope: all 33 files under `.kiro/` (three steering files plus requirements/design/tasks for ten features), `docs/BRD.md`, decisions, mapping, technical spec and detailed design, and the runtime prompt definitions. This is a source-and-status inventory, not evidence of successful cloud deployment.

## Existing product contract

- Keep Flask, the existing three-persona UI, `/api` and keyed `/hsds` APIs.
- Preserve original raw bytes and validate official HSDS v3.2.3. The original whole-source quarantine requirement was superseded by the user's 2026-11-04 instruction after comparing the old engine: isolate invalid objects and dependent children, commit the accepted graph atomically, and report both source-record and object counts, including partial imports.
- Re-import deterministically; preserve human edits and open conflicts instead of silently overwriting them.
- AI creates evidence-backed proposals; humans approve changes to live HSDS data. Source-only reconciliation remains as specified in the existing ingest design.
- Preserve consent, provider organization boundaries, document approval, and the single `user_reported` flag / next-run recheck behavior.
- Keep the seeded maintenance thresholds (at least 95% detection, at most 5% false flags); do not lower them to accommodate an integration regression.
- Spreadsheet ingestion, semantic search and multilingual features remain unimplemented stretch work.

## Prompt inventory

There is no separate prompt directory or prompt file in this checkout. Runtime prompts are Python constants:

| Definition | Role | Status and required checks |
|---|---|---|
| `app/services/chat.py::SYSTEM` | Context-only short plain-language seeker answers | Active for Bedrock chat; rules/mock path makes no model call. Preserve context grounding, refusal when missing evidence, consent outside the model, and policy citations. |
| `app/maintenance/extractor.py::SYSTEM_PROMPT_TEMPLATE`, `FACT_SCHEMA` | Production maintenance facts with verbatim quotations | Active when `LLM_BACKEND=bedrock`; random page boundary treats page text as untrusted; validators verify quote/value support. Keep the existing field schema and closure-vs-hours distinction. |
| `app/services/extract.py::LLMExtractor.SYSTEM`, `SCHEMA` | Earlier fact extractor shape (`snip`, display values) | A retained older implementation. The current maintenance service uses the ported grounded extractor for real model calls and `RuleExtractor` for offline input. Do not mistake this retained class for a second active maintenance pipeline. |
| `.kiro/specs/spreadsheet-ingestion/design.md` | Planned model-assisted column mapping | Design only; no implemented runtime prompt. |

Model/request settings live in `app/services/llm.py` and `app/maintenance/extractor.py::BedrockInvoker`. The latter supports `RE_MODEL_TEMPERATURE=omit`; model ID, region and sampling must be aligned through settings. Real Bedrock behavior remains unchecked until the account is connected and a call succeeds.

If a prompt changes, update this inventory, the owning feature's design/tasks, the relevant technical spec and regression/evaluation coverage. Never mark a real-model evaluation complete based solely on a fake invoker or rule extractor.

## Differences to reconcile

| Area | Previous document state | Integration decision / verification still needed |
|---|---|---|
| HSDS | Steering and technical spec describe a handwritten subset and whole-source quarantine | Restore official schemas, core transforms/IDs and the old engine's per-object/parent-cascade quarantine. Keep richer FINAL fields only if they validate. The user authorized changing the earlier whole-source policy; accepted writes remain atomic. |
| Time zone | Docs use an IANA string in HSDS `schedule.timezone` | Official schema requires a numeric value there. Preserve IANA/local times in `x_resource_engine.local_schedule`; emit offset times. Update mapping and tests together. |
| Approvals | Stale guard checked off, no explicit concurrency requirements | Restore atomic pending-decision claim, resource locking/version CAS and history transaction from the original engine; add concurrent verification. |
| Migrations | ADR-2 says JSON documents avoid schema migrations | JSON reduces resource-shape migrations; workflow columns/tables still require versioned migrations. Preserve IDs and historical audit. |
| Jobs | Same-image Fargate design exists; web can execute synchronously | Fix CLI boolean arguments, persist job/task status and failures; keep production web requests asynchronous. |
| Auth | Local/Cognito implementations exist; real Cognito unchecked | Add signed short-lived first-password/MFA challenges and UI. Actual Cognito remains unchecked until cloud validation. |
| Toolchain | pip requirements + unittest | User requested uv. `pyproject.toml`/`uv.lock` become the dependency source for local, CI and image builds. |
| AWS | Persistent OIDC deployment assumed | User's account is an expiring Workshop Studio account. Prepare an explicit workshop path using temporary credentials and export/redeployment instructions; retain the production OIDC path. Never treat an expired event account as persistent hosting. |
| Testing | README/test plan state 40 tests | Baseline checkout actually has 57; first review found an intermittent stale error. Publish current observed results after integration. |

## Documentation update contract

Every behavior/configuration change in this integration must include its matching `.kiro/specs/<feature>/{requirements,design,tasks}.md`, steering changes when architecture/toolchain shifts, and the relevant `docs/` page. Separate “implemented” from “locally tested”, “PostgreSQL tested”, “Terraform validated”, and “applied in AWS”. Keep unchecked items unchecked until their evidence exists.

ADR-9's “shared-file freeze” describes the historical maintenance-port PR. The user's 2026-11-04 instruction explicitly authorizes changes to schemas, store, proposals, database, auth and jobs for this integration; that historical freeze is not a prohibition on the requested repairs.

The only deployment source repository is `https://github.com/alina-cheng/resource_engine`. The original `onedegree_resource_engine` directory and sibling `local_refs` are local references, not publishable deployment content. New tests/docs belong inside FINAL; credentials, local databases, Terraform state/plans and workshop exports stay ignored.
