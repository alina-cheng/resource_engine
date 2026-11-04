"""User reports -- the trigger for an on-demand maintenance recheck.

A report is a human saying "something about this listing looks wrong". One report is enough:
the record is selected for the next maintenance run and the single ``user_reported`` flag is
raised for a specialist regardless of what the check finds. The report respects the
page-hash skip -- the AI re-reviews only if the page changed since the last review, but the
human-review flag is raised either way (a person looks because a person flagged it; detection
only proposes, a person decides). This is all maintenance-owned; the report table and the HTTP
endpoint are thin additive surfaces in db.py / routes_app.py.
"""
from __future__ import annotations

from app.db import Database, new_id, now_iso

# The single review flag raised whenever a user report is present. It replaces the two flags
# the source engine used (legitimacy vs reports-on-unchanged-page): any report means a human
# should look, full stop.
USER_REPORTED_FLAG = "user_reported"


class ReportService:
    """Records user reports and exposes which records have open ones."""

    def __init__(self, db: Database):
        self.db = db

    def file(self, resource_id: str, *, reporter_id: str | None, reporter_email: str | None,
             note: str | None = None) -> dict:
        """Record a report. Returns the stored row (id + status)."""
        rid = new_id()
        self.db.run(
            "INSERT INTO user_report (id,resource_id,reporter_id,reporter_email,note,created_at,status) "
            "VALUES (?,?,?,?,?,?, 'open')",
            (rid, resource_id, reporter_id, reporter_email, (note or "").strip()[:1000], now_iso()))
        return {"id": rid, "resource_id": resource_id, "status": "open"}

    def open_resource_ids(self) -> set[str]:
        """Service ids with at least one open report: these are selected into the next run and
        flagged for a human; the AI re-reviews only if the page changed (hash-skip applies)."""
        return {r["resource_id"] for r in
                self.db.q("SELECT DISTINCT resource_id FROM user_report WHERE status='open'")}

    def has_open(self, resource_id: str) -> bool:
        return bool(self.db.one(
            "SELECT 1 AS x FROM user_report WHERE resource_id=? AND status='open' LIMIT 1", (resource_id,)))

    def list(self, *, status: str | None = "open", limit: int = 300) -> list[dict]:
        where, params = [], []
        if status:
            where.append("status=?"); params.append(status)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        return self.db.q(
            f"SELECT * FROM user_report{clause} ORDER BY created_at DESC LIMIT ?", params + [limit])

    def counts_by_resource(self, resource_ids: list[str]) -> dict[str, int]:
        if not resource_ids:
            return {}
        placeholders = ",".join("?" * len(resource_ids))
        rows = self.db.q(
            f"SELECT resource_id, COUNT(*) AS n FROM user_report "
            f"WHERE status='open' AND resource_id IN ({placeholders}) GROUP BY resource_id",
            resource_ids)
        return {r["resource_id"]: r["n"] for r in rows}

    def resolve_for(self, resource_id: str, resolved_by: str, run_id: str | None = None) -> int:
        """Mark a record's open reports resolved once it has been rechecked. Returns how many."""
        open_rows = self.db.q(
            "SELECT id FROM user_report WHERE resource_id=? AND status='open'", (resource_id,))
        for row in open_rows:
            self.db.run(
                "UPDATE user_report SET status='resolved', resolved_by=?, resolved_at=?, run_id=? WHERE id=?",
                (resolved_by, now_iso(), run_id, row["id"]))
        return len(open_rows)
