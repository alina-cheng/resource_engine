# Design: AI maintenance worker

- **Detection engine** `app/maintenance/` (ported from the One Degree monorepo, see `docs/decisions.md` ADR-9): `extractor.py` (rule + grounded Bedrock fact extraction with verbatim-quote anti-hallucination), `comparator.py` (structured-fact comparison, category precedence, triage), `worker.py` (review-need hashing), `findings.py` (Finding/Evidence/Category + `finding_problems`). Framework-free; depends only on `app.maintenance` + `app.hsds.ids`.
- `app/services/website.py` source interface: sample (default) and live (user agent, robots.txt, per-host rate limit).
- `app/services/extract.py` rule extractor (offline fact source feeding the ported comparator when the LLM is a mock).
- `app/services/maintenance_bridge.py` implements the engine's three ports (website source, HSDS record reader via `app/hsds/nest`, findings sink) over resource-engine services; translates engine findings into `ai_finding` change requests.
- `app/services/maintenance.py` drives the engine; `check_result` stores latest result, page hash, record version and review `flags`.
- **User reports** `app/maintenance/reports.py` (`ReportService`): `user_report` table; a report forces a recheck and raises the single `user_reported` flag. Endpoints `POST /api/reports`, `GET /admin/reports`, resolve, in `app/web/routes_app.py`; admin "Reports" view in `frontend/admin.js`.
- Scheduling: EventBridge Scheduler runs `python -m app.jobs.run maintenance`.
- Integration preserves exact missing-field baselines (None is not changed into []), converts hours/accessibility proposals to valid typed HSDS, includes per-service location-link hours in comparisons, and recognizes original NDP county descriptions. Maintenance failures close the run as failed; batch limits also bound report-forced checks. Prompt text/grounding behavior is unchanged; configured model ID is passed explicitly to BedrockInvoker.

See `docs/decisions.md` (ADR-9, ADR-10) for the port and report-trigger decisions, `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
