"""Prepare/verify a durable marker around an actual PostgreSQL container restart."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.adapters.base import SourceConfig
from app.config import load_settings
from app.container import build_container
from app.db import new_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "verify"])
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql://"):
        raise SystemExit("Set TEST_DATABASE_URL to the local review PostgreSQL database.")
    settings = load_settings().with_overrides(database_url=url, data_dir=ROOT / "var/postgres-verification")
    c = build_container(settings)
    receipt_path = settings.data_dir / "restart-receipt.json"
    if args.phase == "prepare":
        run = c.ingest.run(SourceConfig("odrs", "odrs", str(ROOT / "data/samples/BayesExport_20250729.json")), "test", "restart-verification")
        assert run["status"] == "completed" and run["stored"] == 50
        row = c.store.list("service", source="odrs", limit=1)[0][0]
        marker = "restart-proof-" + new_id()
        c.store.apply_patch(row["id"], {"fees_description": "Before " + marker}, "admin", "restart-verification", expected_version=row["version"])
        cid = c.proposals.create(resource_id=row["id"], resource_type="service", org_id=row["org_id"], kind="provider_update",
            proposed_by_type="provider", proposed_by="restart-verification",
            patch={"fees_description": {"current": "Before " + marker, "proposed": marker}})
        c.proposals.approve(cid, "restart-verification")
        current = c.store.get(row["id"])
        receipt = {"id": row["id"], "marker": marker, "version": current["version"], "proposal": cid,
                   "counts": c.store.counts(), "history_count": len(c.store.history(row["id"]))}
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"phase": "prepared", "database": c.db.kind, "counts": receipt["counts"]}))
    else:
        receipt = json.loads(receipt_path.read_text())
        row = c.store.get(receipt["id"])
        assert row["data"]["fees_description"] == receipt["marker"]
        assert row["version"] == receipt["version"]
        assert c.proposals.get(receipt["proposal"])["status"] == "applied"
        assert c.store.counts() == receipt["counts"]
        assert len(c.store.history(row["id"])) == receipt["history_count"]
        print(json.dumps({"phase": "verified_after_restart", "database": c.db.kind,
                          "record": row["id"], "version": row["version"], "approval": "applied", "history": "preserved"}))


if __name__ == "__main__":
    main()
