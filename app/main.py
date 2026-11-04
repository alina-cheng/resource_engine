"""Web entry point. Local: `python -m app.main`. Container: gunicorn app.main:app."""
from __future__ import annotations
import os
import threading
import time

from app.container import build_container
from app.web import create_app

_container = build_container()
app = create_app(container=_container)


def _scheduler(c):
    """Local convenience scheduler. On AWS, EventBridge Scheduler runs these jobs as ECS tasks instead."""
    last = {"import": 0.0, "maintenance": 0.0}
    every = {"import": c.settings.import_interval_minutes * 60, "maintenance": c.settings.maintenance_interval_minutes * 60}
    while True:
        now = time.time()
        for job in ("import", "maintenance"):
            if now - last[job] >= every[job]:
                last[job] = now
                try:
                    c.jobs._do(job, {"who": "scheduler"})
                except Exception as e:  # noqa: BLE001
                    print(f"scheduled {job} failed: {e}")
        time.sleep(30)


if _container.settings.scheduler_enabled:
    threading.Thread(target=_scheduler, args=(_container,), daemon=True).start()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")), threaded=True)
