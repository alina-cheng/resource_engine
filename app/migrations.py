"""Versioned, transactional upgrades for existing SQLite and PostgreSQL databases."""
from app.db import dumps, loads, new_id, now_iso
from app.hsds.normalize import normalize_document


def migrate(tx):
    applied = {r["version"] for r in tx.q("SELECT version FROM schema_migration")}
    if 1 not in applied:
        if tx.db.kind == "postgres":
            columns = {r["column_name"] for r in tx.q(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='check_result'")}
        else:
            columns = {r["name"] for r in tx.q("PRAGMA table_info(check_result)")}
        if "flags" not in columns:
            tx.run("ALTER TABLE check_result ADD COLUMN flags TEXT")
        tx.run("INSERT INTO schema_migration (version,applied_at) VALUES (?,?)", (1, now_iso()))
    if 2 not in applied:
        # Preserve existing public IDs, human edits, provenance and historical audit rows.
        for row in tx.q("SELECT * FROM resource"):
            before = loads(row["data"])
            after = normalize_document(before, row["type"])
            if before == after:
                continue
            tx.run("UPDATE resource SET data=?, version=version+1, updated_at=? WHERE id=?",
                   (dumps(after), now_iso(), row["id"]))
            tx.run("INSERT INTO change_history (id,resource_id,resource_type,field_name,previous_value,replacement_value,last_action_type,last_action_date,actor_type,updated_by,note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (new_id(), row["id"], row["type"], "*", dumps(before), dumps(after), "update", now_iso(True), "system", "schema-migration-2", "Official HSDS compatibility; resource IDs preserved"))
        for row in tx.q("SELECT resource_id,source,snapshot FROM resource_source WHERE snapshot IS NOT NULL"):
            kind = tx.one("SELECT type FROM resource WHERE id=?", (row["resource_id"],))
            if kind:
                snapshot = normalize_document(loads(row["snapshot"]), kind["type"])
                tx.run("UPDATE resource_source SET snapshot=? WHERE resource_id=? AND source=?",
                       (dumps(snapshot), row["resource_id"], row["source"]))
        tx.run("INSERT INTO schema_migration (version,applied_at) VALUES (?,?)", (2, now_iso()))
    if 3 not in applied:
        if tx.db.kind == "postgres":
            columns = {r["column_name"] for r in tx.q(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='check_result'")}
        else:
            columns = {r["name"] for r in tx.q("PRAGMA table_info(check_result)")}
        if "record_hash" not in columns:
            tx.run("ALTER TABLE check_result ADD COLUMN record_hash TEXT")
        tx.run("INSERT INTO schema_migration (version,applied_at) VALUES (?,?)", (3, now_iso()))
