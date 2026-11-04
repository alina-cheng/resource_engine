# Design: AI maintenance worker

- `app/services/website.py` source interface: sample (default) and live (user agent, robots.txt, per-host rate limit).
- `app/services/extract.py` rule extractor and Bedrock extractor behind one output shape.
- `app/services/maintenance.py` compare + categorise + create findings; `check_result` stores latest result, page hash and record version.
- Scheduling: EventBridge Scheduler runs `python -m app.jobs.run maintenance`.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
