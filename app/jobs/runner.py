"""Durable job status shared by local threads and one-off ECS tasks."""
from __future__ import annotations
import os
import threading
from app.db import dumps, loads, new_id, now_iso


class JobError(Exception):
    pass


class JobRunner:
    def __init__(self, container):
        self.c = container

    def _do(self, kind: str, params: dict) -> dict:
        c = self.c
        if kind == "import":
            return {"results": c.ingest_all("manual", params.get("who", "admin"), params.get("source"))}
        if kind == "maintenance":
            return c.maintenance.run(scope=params.get("scope", "all"), service_id=params.get("service_id"),
                trigger="manual", initiated_by=params.get("who", "admin"), limit=params.get("limit"),
                force=bool(params.get("force")))
        if kind == "reindex":
            return c.search.reindex()
        raise ValueError(f"unknown job {kind}")

    def create(self, kind, params):
        if kind not in {"import", "maintenance", "reindex"}:
            raise ValueError(f"unknown job {kind}")
        jid = new_id()
        self.c.db.run("INSERT INTO job_run (id,kind,status,params,created_at) VALUES (?,?,'queued',?,?)",
                      (jid, kind, dumps(params), now_iso()))
        return jid

    def get(self, jid):
        row = self.c.db.one("SELECT * FROM job_run WHERE id=?", (jid,))
        if row:
            row["params"] = loads(row["params"], {})
            row["result"] = loads(row["result"], {})
        return row

    def execute(self, jid):
        won = self.c.db.run("UPDATE job_run SET status='running', started_at=? WHERE id=? AND status='queued'",
                             (now_iso(), jid))
        if not won:
            raise JobError("Job was already claimed or does not exist.")
        row = self.get(jid)
        try:
            out = self._do(row["kind"], row["params"])
            if any(r.get("status") == "failed" for r in out.get("results", [])):
                self.c.db.run("UPDATE job_run SET result=? WHERE id=?", (dumps(out), jid))
                raise JobError("One or more imports failed; inspect import runs.")
        except Exception as error:
            self.c.db.run("UPDATE job_run SET status='failed',finished_at=?,error=? WHERE id=?",
                           (now_iso(), f"{type(error).__name__}: {error}"[:2000], jid))
            raise
        self.c.db.run("UPDATE job_run SET status='completed',finished_at=?,result=? WHERE id=?",
                       (now_iso(), dumps(out), jid))
        return {"started": True, "finished": True, "job_id": jid, **out}

    def _background(self, jid):
        try:
            self.execute(jid)
        except Exception:
            pass  # execute persisted the failure for the authenticated status API.

    def start(self, kind: str, wait: bool = False, **params) -> dict:
        jid = self.create(kind, params)
        # AWS requests always return immediately, including legacy clients' wait:true.
        if os.environ.get("JOB_RUNNER") == "ecs":
            try:
                import boto3
                ecs = boto3.client("ecs", region_name=self.c.settings.aws_region)
                cmd = ["python", "-m", "app.jobs.run", kind, f"--job-id={jid}"]
                response = ecs.run_task(cluster=os.environ["ECS_CLUSTER"],
                    taskDefinition=os.environ["JOB_TASK_DEFINITION"], launchType="FARGATE",
                    networkConfiguration={"awsvpcConfiguration": {
                        "subnets": os.environ["JOB_SUBNETS"].split(","),
                        "securityGroups": os.environ["JOB_SECURITY_GROUPS"].split(","), "assignPublicIp": "ENABLED"}},
                    overrides={"containerOverrides": [{"name": "app", "command": cmd}]})
                tasks = response.get("tasks", [])
                if response.get("failures") or not tasks:
                    raise JobError("ECS did not start the task. Check task capacity and permissions.")
                arn = tasks[0]["taskArn"]
                self.c.db.run("UPDATE job_run SET task_arn=? WHERE id=?", (arn, jid))
                return {"started": True, "finished": False, "runner": "ecs", "job_id": jid, "task_arn": arn}
            except Exception as error:
                self.c.db.run("UPDATE job_run SET status='failed',finished_at=?,error=? WHERE id=?",
                               (now_iso(), f"{type(error).__name__}: {error}"[:2000], jid))
                raise JobError("The job could not be started. See its status and CloudWatch logs.") from error
        if wait:
            return self.execute(jid)
        threading.Thread(target=self._background, args=(jid,), daemon=True).start()
        return {"started": True, "finished": False, "runner": "thread", "job_id": jid}
