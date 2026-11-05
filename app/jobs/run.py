"""Job entry point: python -m app.jobs.run import|maintenance|reindex|seed-demo [options]
Used by ECS scheduled tasks (EventBridge Scheduler), by the Makefile and by operators."""
from __future__ import annotations
import argparse
import json

from app.container import build_container


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="app.jobs.run")
    ap.add_argument("job", choices=["import", "maintenance", "reindex", "seed-demo"])
    ap.add_argument("--source")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--scope", default="all")
    ap.add_argument("--service-id")
    ap.add_argument("--who", default="scheduler")
    ap.add_argument("--job-id")
    ap.add_argument("--no-maintenance", action="store_true", help="seed-demo: skip the AI website check")
    a = ap.parse_args(argv)
    c = build_container()
    if a.job == "seed-demo":
        from tools.sample_data_generator.seed import seed_demo
        print(json.dumps(seed_demo(c, run_maintenance=not a.no_maintenance, maintenance_limit=a.limit),
                         indent=2, default=str))
        return 0
    from app.jobs.runner import JobRunner
    runner = JobRunner(c)
    if a.job_id:
        row = runner.get(a.job_id)
        if not row or row["kind"] != a.job:
            ap.error("job ID does not match the requested job")
        jid = a.job_id
    else:
        jid = runner.create(a.job, dict(source=a.source, limit=a.limit, force=a.force, scope=a.scope,
                                       service_id=a.service_id, who=a.who))
    try:
        out = runner.execute(jid)
    except Exception:
        print(json.dumps({"job_id": jid, "status": "failed"}))
        return 1
    print(json.dumps(out, indent=2, default=str))
    failed = [r for r in out.get("results", []) if r.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
