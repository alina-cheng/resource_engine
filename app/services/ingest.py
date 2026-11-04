"""Ingest pipeline (priority 1): fetch -> raw store -> map -> validate -> upsert / quarantine.

Guarantees (R1.3-R1.7): every payload is kept as received; a record that cannot be turned into
valid HSDS is quarantined with the reason (never dropped, never stored invalid); re-running updates
instead of duplicating; and received == stored + quarantined for every run."""
from __future__ import annotations
import json
from typing import Any

from app.adapters.base import MappingError, SourceConfig
from app.adapters.registry import build_adapter
from app.db import Database, dumps, new_id, now_iso
from app.services.proposals import ChangeRequests
from app.services.store import HsdsStore, ValidationFailed


class IngestService:
    def __init__(self, settings, db: Database, store: HsdsStore, blob, proposals: ChangeRequests):
        self.settings, self.db, self.store, self.blob, self.proposals = settings, db, store, blob, proposals

    def run(self, cfg: SourceConfig, trigger: str = "scheduled", initiated_by: str = "scheduler",
            since: str | None = None) -> dict[str, Any]:
        run_id, started = new_id(), now_iso()
        self.db.run("INSERT INTO import_run (id,source,trigger,initiated_by,started_at,status) VALUES (?,?,?,?,?,'running')",
                    (run_id, cfg.name, trigger, initiated_by, started))
        adapter = build_adapter(cfg, self.settings)
        counts = {"received": 0, "stored": 0, "quarantined": 0, "clashes": 0, "created": 0, "updated": 0, "unchanged": 0,
                  "shared_disagreements": 0}
        seen: dict[str, str] = {}   # resource id -> hash of first version seen in this run
        status, error = "completed", None
        try:
            for batch in adapter.fetch(since):
                key = self.blob.put(f"raw/{cfg.name}/{started}/{batch.batch_id}", batch.raw)   # as received (R1.3)
                self.db.run("INSERT INTO raw_payload (id,source,native_id,fetched_at,blob_key,run_id) VALUES (?,?,?,?,?,?)",
                            (new_id(), cfg.name, batch.batch_id, started, key, run_id))
                for rec in batch.records:
                    counts["received"] += 1
                    self._one(adapter, cfg, rec, started, run_id, counts, seen)
        except Exception as e:  # noqa: BLE001 - fetch-level failure; counts so far remain truthful
            status, error = "failed", f"{type(e).__name__}: {e}"
        balanced = counts["received"] == counts["stored"] + counts["quarantined"]
        if status == "completed" and not balanced:
            status, error = "failed", "count mismatch: received != stored + quarantined"
        self.db.run("UPDATE import_run SET finished_at=?, status=?, received=?, stored=?, quarantined=?, clashes=?, detail=? WHERE id=?",
                    (now_iso(), status, counts["received"], counts["stored"], counts["quarantined"], counts["clashes"],
                     dumps({"error": error, **counts}), run_id))
        return {"run_id": run_id, "source": cfg.name, "status": status, "error": error, **counts}

    def _one(self, adapter, cfg, rec, fetched_at, run_id, counts, seen) -> None:
        nid = "?"
        try:
            nid = adapter.native_id(rec)
            mapped = adapter.map(rec)
            errors: list[str] = []
            for r in mapped.resources:
                errors += self.store.validate_resource(r.type, r.data)
            if errors:
                raise MappingError("; ".join(errors[:5]))
            clashes, actions = [], []
            with self.db.tx() as t:                         # one source record = one atomic unit
                for r in mapped.resources:
                    # Organizations, locations and taxonomy terms are shared by many source records.
                    # First version seen in a run wins; later disagreements are counted, not flip-flopped.
                    h = dumps(r.data)
                    if r.id in seen:
                        if seen[r.id] != h:
                            counts["shared_disagreements"] += 1
                        continue
                    seen[r.id] = h
                    out = self.store.ingest_upsert(t, cfg.name, nid, fetched_at, r, run_id)
                    actions.append(out["action"])
                    if out["clashes"]:
                        clashes.append((r, out["clashes"]))
                for r, cl in clashes:
                    for c in cl:
                        self.proposals.create(
                            resource_id=r.id, resource_type=r.type, org_id=r.org_id, kind="conflict",
                            proposed_by_type="source", proposed_by=cfg.name,
                            patch={c["field"]: {"current": c["current"], "proposed": c["proposed"], "base": c["base"]}},
                            title=f"Source update clashes with a manual or AI change to '{c['field']}'", tx=t)
            counts["stored"] += 1
            counts["clashes"] += sum(len(cl) for _, cl in clashes)
            k = "created" if "created" in actions else "updated" if "updated" in actions else "unchanged"
            counts[k] += 1
        except (MappingError, ValidationFailed, KeyError, ValueError, TypeError) as e:
            counts["quarantined"] += 1
            self.db.run("INSERT INTO quarantine (id,run_id,source,native_id,reason,payload,created_at) VALUES (?,?,?,?,?,?,?)",
                        (new_id(), run_id, cfg.name, nid, f"{type(e).__name__}: {e}", json.dumps(rec, ensure_ascii=False)[:200000], now_iso()))
