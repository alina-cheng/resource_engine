"""Application API used by the web UI: seeker, provider and admin personas."""
from __future__ import annotations
import json

from flask import Blueprint, g, jsonify, request

from app.db import loads, new_id, now_iso
from app.hsds.nest import Views
from app.services.users import AuthError
from app.web import auth_required, container, current_principal, err
from app.web.routes_hsds import hash_key, new_api_key

bp = Blueprint("app", __name__)


def body() -> dict:
    return request.get_json(silent=True) or {}


def _in(ids: list) -> str:
    return ",".join("?" * len(ids)) if ids else "NULL"


def _pg() -> tuple[int, int]:
    try:
        return max(1, int(request.args.get("page", 1))), min(200, max(1, int(request.args.get("per_page", 25))))
    except ValueError:
        return 1, 25


def _name(row: dict | None) -> str | None:
    return (row or {}).get("data", {}).get("name")


# ---------------------------------------------------------------------------------------------- public
@bp.get("/health")
def health():
    c = container()
    return jsonify({"status": "ok", "hsds_version": c.settings.hsds_version, "validator": c.validator.engine(),
                    "auth": c.settings.auth_mode, "llm": c.llm.name, "search": c.search.services.name,
                    "database": c.db.kind, "blob": c.settings.blob_backend})


@bp.post("/auth/login")
def login():
    b = body()
    return jsonify(container().auth.login(b.get("email", ""), b.get("password", "")))


@bp.post("/auth/challenge")
def login_challenge():
    auth, b = container().auth, body()
    if auth.mode != "cognito":
        return err(400, "This login method does not use challenges.")
    return jsonify(auth.respond_challenge(b.get("challenge_token", ""), b.get("answer", ""), b.get("attributes")))


@bp.post("/auth/register")
def register():
    b = body()
    if not b.get("email") or not b.get("name"):
        return err(400, "Enter your name and email.")
    return jsonify(container().auth.register_seeker(b["email"], b["name"], b.get("password", "")))


@bp.get("/auth/me")
@auth_required()
def me():
    p, c = g.principal, container()
    out = {"id": p.id, "email": p.email, "name": p.name, "role": p.role, "org_id": p.org_id}
    if p.org_id:
        out["org_name"] = _name(c.store.get(p.org_id))
    return jsonify(out)


# ---------------------------------------------------------------------------------------------- chat
@bp.post("/chat")
def chat():
    b = body()
    msg = (b.get("message") or "").strip()
    if not msg:
        return err(400, "Type a message first.")
    return jsonify(container().chat.handle(current_principal(), b.get("session_id"), msg[:1000]))


@bp.get("/chat/history")
def chat_history():
    p = current_principal()
    return jsonify({"messages": container().chat.history(request.args.get("session_id", ""), p.id if p else None)})


@bp.post("/chat/resume")
@auth_required("seeker")
def chat_resume():
    return jsonify(container().chat.resume(g.principal, body().get("session_id", "")))


@bp.post("/chat/confirm")
@auth_required("seeker")
def chat_confirm():
    b = body()
    return jsonify(container().chat.confirm_request(g.principal, b.get("session_id", ""), b.get("service_id", "")))


# ---------------------------------------------------------------------------------------------- seeker
@bp.get("/seeker/profile")
@auth_required("seeker")
def seeker_profile():
    return jsonify(container().seekers.get_profile(g.principal.id))


@bp.put("/seeker/profile")
@auth_required("seeker")
def seeker_profile_save():
    return jsonify(container().seekers.save_profile(g.principal.id, body()))


@bp.get("/seeker/requests")
@auth_required("seeker")
def seeker_requests():
    return jsonify({"requests": container().seekers.my_requests(g.principal.id)})


@bp.get("/search")
@auth_required("seeker", "provider", "admin")
def search_directory():
    c, q = container(), request.args.get("q", "")
    hits = c.search.search_services(q, filters={"status": "active"}, limit=10)
    return jsonify({"results": [c.chat._card(h) for h in hits]})


# ---------------------------------------------------------------------------------------------- user reports
@bp.post("/reports")
@auth_required("seeker", "provider", "admin")
def file_report():
    """Any signed-in user can report a listing that looks wrong. The report selects the record
    for the next maintenance run and raises the `user_reported` flag for a specialist; the AI
    re-reviews only if the page changed since the last review (it respects the hash-skip)."""
    c, b, p = container(), body(), g.principal
    rid = (b.get("resource_id") or "").strip()
    row = c.store.get(rid)
    if not row or row["type"] != "service":
        return err(404, "That service could not be found.")
    r = c.maintenance.reports.file(rid, reporter_id=p.id, reporter_email=p.email, note=b.get("note"))
    return jsonify({**r, "message": "Thanks. A specialist will review this listing."}), 201


# ---------------------------------------------------------------------------------------------- provider
def _own(rid: str) -> dict:
    row = container().store.get(rid)
    if not row or row["type"] not in ("organization", "service", "location"):
        raise KeyError(rid)
    if row["org_id"] != g.principal.org_id:
        raise PermissionError("That record belongs to another organization.")
    return row


def _org_bundle(org_id: str) -> dict:
    c = container()
    org = c.store.get(org_id)
    if not org:
        raise KeyError(org_id)
    services, _ = c.store.list("service", org_id=org_id, limit=500)
    sals = [loads(r["data"]) for r in c.db.q("SELECT data FROM resource WHERE type='service_at_location' AND deleted=0 AND org_id=?", (org_id,))]
    locs = list(c.store.get_many(list({s["location_id"] for s in sals})).values())
    checks = {r["resource_id"]: r for r in c.db.q("SELECT * FROM check_result WHERE org_id=?", (org_id,))}
    pend = c.db.q("SELECT resource_id, COUNT(*) AS n FROM change_request WHERE org_id=? AND status='pending' GROUP BY resource_id", (org_id,))
    pmap = {r["resource_id"]: r["n"] for r in pend}
    return {"organization": org, "services": [{**s, "check": checks.get(s["id"]), "pending": pmap.get(s["id"], 0)} for s in services],
            "locations": [{**l, "pending": pmap.get(l["id"], 0)} for l in locs], "org_pending": pmap.get(org_id, 0)}


@bp.get("/provider/organization")
@auth_required("provider")
def provider_org():
    if not g.principal.org_id:
        return err(409, "Your account is not linked to an organization yet. Ask a One Degree admin.")
    return jsonify(_org_bundle(g.principal.org_id))


@bp.get("/provider/records/<rid>")
@auth_required("provider")
def provider_record(rid):
    c, row = container(), _own(rid)
    return jsonify({"record": row, "history": c.store.history(rid, 50),
                    "change_requests": c.proposals.list(resource_id=rid, limit=20)})


@bp.post("/provider/change-requests")
@auth_required("provider")
def provider_cr():
    c, b = container(), body()
    row = _own(b.get("resource_id", ""))
    patch = b.get("patch") or {}
    if not patch:
        return err(400, "Change at least one field.")
    errors = c.store.validate_patch(row["id"], patch)
    if errors:
        return err(422, "That change would produce invalid HSDS data.", details=errors)
    cur = row["data"]
    cid = c.proposals.create(resource_id=row["id"], resource_type=row["type"], org_id=row["org_id"], kind="provider_update",
                             proposed_by_type="provider", proposed_by=g.principal.email,
                             patch={f: {"current": cur.get(f), "proposed": v} for f, v in patch.items()},
                             title=f"Update to {row['data'].get('name', row['type'])} from {g.principal.name}")
    return jsonify({"id": cid, "status": "pending"}), 201


@bp.get("/provider/change-requests")
@auth_required("provider")
def provider_crs():
    return jsonify({"change_requests": container().proposals.list(org_id=g.principal.org_id, limit=100)})


@bp.get("/provider/needs")
@auth_required("provider")
def provider_needs():
    return jsonify(container().seekers.provider_needs(g.principal.org_id))


@bp.get("/provider/served")
@auth_required("provider")
def provider_served():
    return jsonify({"served": container().seekers.provider_served(g.principal.org_id)})


@bp.post("/provider/requests/<rid>/respond")
@auth_required("provider")
def provider_respond(rid):
    b = body()
    if b.get("action") not in ("accept", "decline", "close"):
        return err(400, "Choose accept, decline or close.")
    return jsonify(container().seekers.respond(g.principal.org_id, rid, b["action"], b.get("note"), b.get("service_id")))


def _upload(auto: bool, org_id: str | None):
    c = container()
    f = request.files.get("file")
    if not f or not f.filename:
        return err(400, "Choose a file to upload.")
    doc = c.documents.upload(filename=f.filename, data=f.read(), title=request.form.get("title") or f.filename,
                             uploaded_by=g.principal.email, org_id=org_id, service_id=request.form.get("service_id") or None,
                             visibility=request.form.get("visibility", "public"), effective_date=request.form.get("effective_date") or None,
                             auto_approve=auto, content_type=f.mimetype)
    return jsonify(doc), 201


@bp.post("/provider/documents")
@auth_required("provider")
def provider_upload():
    return _upload(False, g.principal.org_id)


@bp.get("/provider/documents")
@auth_required("provider")
def provider_docs():
    return jsonify({"documents": container().documents.list(org_id=g.principal.org_id)})


# ---------------------------------------------------------------------------------------------- admin
def _enrich_crs(crs: list[dict]) -> list[dict]:
    c = container()
    rows = c.store.get_many(list({x["resource_id"] for x in crs}))
    for x in crs:
        r = rows.get(x["resource_id"])
        x["resource_name"] = _name(r) or x["resource_type"]
        x["org_name"] = _name(c.store.get(x["org_id"])) if x.get("org_id") else None
        x["stale_fields"] = c.proposals.stale_fields(x) if x["status"] == "pending" else []
    return crs


@bp.get("/admin/stats")
@auth_required("admin")
def admin_stats():
    c = container()
    cats = {r["category"]: r["n"] for r in c.db.q(
        "SELECT c.category, COUNT(*) AS n FROM check_result c JOIN resource r ON r.id=c.resource_id "
        "WHERE r.type='service' AND r.deleted=0 GROUP BY c.category")}
    total_services = c.store.counts().get("service", 0)
    cats["unchecked"] = max(0, total_services - sum(cats.values()))
    stale = c.db.one("SELECT COUNT(*) AS n FROM check_result c JOIN resource r ON r.id=c.resource_id "
                     "WHERE r.type='service' AND r.deleted=0 AND (c.record_version IS NULL OR c.record_version<>r.version)")["n"]
    active_job = c.db.one("SELECT id,status,result FROM job_run WHERE kind='maintenance' AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1")
    if active_job:
        active_job["result"] = loads(active_job["result"], {})
    pend = {r["kind"]: r["n"] for r in c.db.q("SELECT kind, COUNT(*) AS n FROM change_request WHERE status='pending' GROUP BY kind")}
    open_reports = c.db.one("SELECT COUNT(*) AS n FROM user_report WHERE status='open'")["n"]
    return jsonify({"counts": c.store.counts(), "check_categories": cats, "pending_by_kind": pend,
                    "maintenance_coverage": {"total": total_services, "checked": total_services-cats["unchecked"],
                                             "unchecked": cats["unchecked"], "needs_recheck": stale},
                    "maintenance_job": active_job,
                    "open_reports": open_reports,
                    "seekers": c.db.one("SELECT COUNT(*) AS n FROM users WHERE role='seeker'")["n"],
                    "providers": c.db.one("SELECT COUNT(*) AS n FROM users WHERE role='provider'")["n"],
                    "open_requests": c.db.one("SELECT COUNT(*) AS n FROM help_request WHERE status='open'")["n"],
                    "docs_pending": c.db.one("SELECT COUNT(*) AS n FROM document WHERE status='pending'")["n"],
                    "quarantined": c.db.one("SELECT COUNT(*) AS n FROM quarantine")["n"],
                    "last_imports": c.db.q("SELECT * FROM import_run ORDER BY started_at DESC LIMIT 5"),
                    "last_maintenance": c.db.q("SELECT * FROM maintenance_run ORDER BY started_at DESC LIMIT 3")})


@bp.get("/admin/reports")
@auth_required("admin")
def admin_reports():
    c = container()
    rows = c.maintenance.reports.list(status=request.args.get("status", "open"), limit=300)
    names = c.store.get_many(list({r["resource_id"] for r in rows}))
    for r in rows:
        rec = names.get(r["resource_id"])
        r["resource_name"] = _name(rec) or "service"
        r["org_id"] = (rec or {}).get("org_id")
        r["org_name"] = _name(c.store.get(r["org_id"])) if r.get("org_id") else None
    return jsonify({"reports": rows})


@bp.post("/admin/reports/<report_id>/resolve")
@auth_required("admin")
def admin_report_resolve(report_id):
    c = container()
    c.db.run("UPDATE user_report SET status='resolved', resolved_by=?, resolved_at=? WHERE id=? AND status='open'",
             (g.principal.email, now_iso(), report_id))
    return jsonify({"status": "resolved"})


@bp.get("/admin/seekers")
@auth_required("admin")
def admin_seekers():
    c = container()
    out = []
    for u in c.users.list("seeker"):
        prof = c.seekers.get_profile(u["id"])
        n = c.db.one("SELECT COUNT(*) AS n FROM help_request WHERE seeker_id=?", (u["id"],))["n"]
        out.append({**u, "zip": prof.get("zip"), "shares": bool(prof.get("share_with_providers")), "requests": n})
    return jsonify({"seekers": out})


@bp.get("/admin/seekers/<uid>")
@auth_required("admin")
def admin_seeker(uid):
    c = container()
    u = c.users.get(uid)
    if not u or u["role"] != "seeker":
        raise KeyError(uid)
    return jsonify({"user": u, "profile": c.seekers.get_profile(uid), "requests": c.seekers.my_requests(uid)})


@bp.get("/admin/providers")
@auth_required("admin")
def admin_providers():
    c, (page, per) = container(), _pg()
    rows, total = c.store.list("organization", limit=per, offset=(page - 1) * per, text_filter=request.args.get("q") or None)
    ids = [r["id"] for r in rows]
    svc = {r["org_id"]: r["n"] for r in c.db.q(f"SELECT org_id, COUNT(*) AS n FROM resource WHERE type='service' AND deleted=0 AND org_id IN ({_in(ids)}) GROUP BY org_id", ids)}
    chk: dict = {}
    for r in c.db.q(f"SELECT org_id, category, COUNT(*) AS n FROM check_result WHERE org_id IN ({_in(ids)}) GROUP BY org_id, category", ids):
        chk.setdefault(r["org_id"], {})[r["category"]] = r["n"]
    pend = {r["org_id"]: r["n"] for r in c.db.q(f"SELECT org_id, COUNT(*) AS n FROM change_request WHERE status='pending' AND org_id IN ({_in(ids)}) GROUP BY org_id", ids)}
    return jsonify({"total": total, "page": page, "organizations": [
        {"id": r["id"], "name": r["data"].get("name"), "website": r["data"].get("website"), "source": r["source"],
         "services": svc.get(r["id"], 0), "checks": chk.get(r["id"], {}), "pending": pend.get(r["id"], 0),
         "flags": r["data"].get("x_resource_engine", {}).get("flags", [])} for r in rows]})


@bp.get("/admin/providers/<org_id>")
@auth_required("admin")
def admin_provider(org_id):
    c = container()
    out = _org_bundle(org_id)
    out["users"] = [u for u in c.users.list("provider") if u["org_id"] == org_id]
    out["change_requests"] = _enrich_crs(c.proposals.list(org_id=org_id, limit=50))
    out["documents"] = c.documents.list(org_id=org_id)
    return jsonify(out)


@bp.get("/admin/records/<rid>")
@auth_required("admin")
def admin_record(rid):
    c, row = container(), None
    row = c.store.get(rid)
    if not row:
        raise KeyError(rid)
    return jsonify({"record": row, "history": c.store.history(rid, 100), "check": c.db.one("SELECT * FROM check_result WHERE resource_id=?", (rid,)),
                    "change_requests": _enrich_crs(c.proposals.list(resource_id=rid, limit=30)),
                    "reports": c.db.q("SELECT * FROM user_report WHERE resource_id=? ORDER BY created_at DESC LIMIT 50", (rid,))})


@bp.put("/admin/records/<rid>")
@auth_required("admin")
def admin_edit(rid):
    c, b = container(), body()
    res = c.store.apply_patch(rid, b.get("patch") or {}, "admin", g.principal.email, note=b.get("note"),
                              expected_version=b.get("expected_version"))
    return jsonify(res)


@bp.get("/admin/change-requests")
@auth_required("admin")
def admin_crs():
    a = request.args
    crs = container().proposals.list(status=a.get("status", "pending"), kind=a.get("kind") or None, org_id=a.get("org_id") or None, limit=300)
    return jsonify({"change_requests": _enrich_crs(crs)})


@bp.post("/admin/change-requests/<cid>/approve")
@auth_required("admin")
def admin_approve(cid):
    b = body()
    return jsonify(container().proposals.approve(cid, g.principal.email, b.get("note"), b.get("overrides"), bool(b.get("force"))))


@bp.post("/admin/change-requests/<cid>/reject")
@auth_required("admin")
def admin_reject(cid):
    container().proposals.reject(cid, g.principal.email, body().get("note"))
    return jsonify({"status": "rejected"})


@bp.post("/admin/maintenance/run")
@auth_required("admin")
def admin_maint_run():
    b = body()
    scope = "service" if b.get("service_id") else "all"
    return jsonify(container().jobs.start("maintenance", wait=bool(b.get("wait")) or request.args.get("wait") == "true", scope=scope,
                                          service_id=b.get("service_id"), force=bool(b.get("force")), limit=b.get("limit"), who=g.principal.email))


@bp.get("/admin/jobs/<jid>")
@auth_required("admin")
def admin_job(jid):
    row = container().jobs.get(jid)
    if not row:
        raise KeyError(jid)
    return jsonify(row)


@bp.get("/admin/maintenance/results")
@auth_required("admin")
def admin_maint_results():
    c, a, (page, per) = container(), request.args, _pg()
    where, p = ["r.type='service'", "r.deleted=0"], []
    cat = a.get("category")
    if cat == "unchecked":
        where.append("c.resource_id IS NULL")
    elif cat:
        where.append("c.category=?"); p.append(cat)
    if a.get("q"):
        where.append("LOWER(r.data) LIKE ?"); p.append(f"%{a['q'].lower()}%")
    if a.get("source"):
        where.append("r.source=?"); p.append(a["source"])
    w = " AND ".join(where)
    total = c.db.one(f"SELECT COUNT(*) AS n FROM resource r LEFT JOIN check_result c ON c.resource_id=r.id WHERE {w}", p)["n"]
    rows = c.db.q(f"SELECT r.id, r.org_id, r.source, r.data, r.version, c.category, c.summary, c.url, c.checked_at, c.verified_marker, c.flags "
                  f"FROM resource r LEFT JOIN check_result c ON c.resource_id=r.id WHERE {w} "
                  f"ORDER BY CASE c.category WHEN 'actively_bad' THEN 0 WHEN 'check_failed' THEN 1 WHEN 'discrepancy' THEN 2 "
                  f"WHEN 'missing_information' THEN 3 WHEN 'verified' THEN 5 ELSE 4 END, r.id LIMIT ? OFFSET ?", p + [per, (page - 1) * per])
    orgs = c.store.get_many(list({r["org_id"] for r in rows if r["org_id"]}))
    ids = [r["id"] for r in rows]
    pend = {r["resource_id"]: r["n"] for r in c.db.q(f"SELECT resource_id, COUNT(*) AS n FROM change_request WHERE status='pending' AND resource_id IN ({_in(ids)}) GROUP BY resource_id", ids)}
    reports = {r["resource_id"]: r["n"] for r in c.db.q(f"SELECT resource_id, COUNT(*) AS n FROM user_report WHERE status='open' AND resource_id IN ({_in(ids)}) GROUP BY resource_id", ids)}
    return jsonify({"total": total, "page": page, "results": [
        {"id": r["id"], "name": loads(r["data"])["name"], "organization": _name(orgs.get(r["org_id"])), "org_id": r["org_id"],
         "source": r["source"], "category": r["category"] or "unchecked", "summary": r["summary"], "url": r["url"],
         "checked_at": r["checked_at"], "verified": bool(r["verified_marker"]), "pending": pend.get(r["id"], 0),
         "flags": loads(r["flags"], []) if "flags" in r.keys() else [], "reports": reports.get(r["id"], 0)} for r in rows]})


@bp.get("/admin/maintenance/runs")
@auth_required("admin")
def admin_maint_runs():
    rows = container().db.q("SELECT * FROM maintenance_run ORDER BY started_at DESC LIMIT 20")
    for r in rows:
        r["counts"] = loads(r["counts"], {})
    return jsonify({"runs": rows})


@bp.post("/admin/imports/run")
@auth_required("admin")
def admin_import_run():
    b = body()
    return jsonify(container().jobs.start("import", wait=bool(b.get("wait")) or request.args.get("wait") == "true", source=b.get("source"), who=g.principal.email))


@bp.get("/admin/imports")
@auth_required("admin")
def admin_imports():
    c = container()
    runs = c.db.q("SELECT * FROM import_run ORDER BY started_at DESC LIMIT 30")
    for r in runs:
        r["balanced"] = r["received"] == r["stored"] + r["quarantined"] if r["status"] != "running" else None
    return jsonify({"runs": runs, "sources": [{"name": s.name, "adapter": s.adapter, "location": s.location, "enabled": s.enabled} for s in c.sources()]})


@bp.post("/admin/imports/upload")
@auth_required("admin")
def admin_import_upload():
    """Import an uploaded source file through the normal ingest pipeline instead of the configured
    location. The uploaded JSON is written to a temporary file and fed to the matching adapter, so
    mapping, validation, raw-payload storage and quarantine behave exactly like a scheduled import."""
    import os
    import tempfile

    from app.adapters.base import SourceConfig
    from app.adapters.registry import ADAPTERS

    c = container()
    f = request.files.get("file")
    if not f or not f.filename:
        return err(400, "Choose a JSON file to upload.")
    # Reuse an existing source's name/adapter so ids, x_resource_engine.source and clash handling
    # match previously imported records. Defaults to the NDP adapter.
    source = (request.form.get("source") or "ndp").strip()
    cfg = next((s for s in c.sources() if s.name == source), None)
    adapter_kind = cfg.adapter if cfg else source
    if adapter_kind not in ADAPTERS:
        return err(400, f"No adapter is registered for '{adapter_kind}'.")

    data = f.read()
    try:
        json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return err(400, "That file is not valid JSON.")

    tmp = tempfile.NamedTemporaryFile(prefix=f"upload-{source}-", suffix=".json", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        upload_cfg = SourceConfig(name=source, adapter=adapter_kind, location=tmp.name, enabled=True,
                                  options=(cfg.options if cfg else {}))
        result = c.ingest.run(upload_cfg, trigger="upload", initiated_by=g.principal.email)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    if c.settings.auto_maintenance_after_import and result.get("status") == "completed" and result.get("received", 0):
        from app.jobs.runner import JobError
        try:
            result["maintenance_job"] = c.jobs.enqueue_maintenance("upload:" + g.principal.email)
        except JobError as error:
            result["maintenance_error"] = str(error)
    return jsonify({**result, "filename": f.filename}), 201


@bp.get("/admin/quarantine")
@auth_required("admin")
def admin_quarantine():
    rows = container().db.q("SELECT id, run_id, source, native_id, reason, created_at FROM quarantine ORDER BY created_at DESC LIMIT 200")
    return jsonify({"quarantine": rows})


@bp.get("/admin/api-keys")
@auth_required("admin")
def admin_keys():
    return jsonify({"keys": container().db.q("SELECT id,name,key_prefix,source_scope,created_by,created_at,revoked_at,last_used_at FROM api_key ORDER BY created_at DESC")})


@bp.post("/admin/api-keys")
@auth_required("admin")
def admin_key_create():
    b, c = body(), container()
    if not b.get("name"):
        return err(400, "Name the key so you can recognize it later.")
    key = new_api_key()
    kid = new_id()
    c.db.run("INSERT INTO api_key (id,name,key_hash,key_prefix,source_scope,created_by,created_at) VALUES (?,?,?,?,?,?,?)",
             (kid, b["name"], hash_key(key), key[:8], b.get("source_scope") or None, g.principal.email, now_iso()))
    return jsonify({"id": kid, "key": key, "note": "Copy this key now. It is not shown again."}), 201


@bp.delete("/admin/api-keys/<kid>")
@auth_required("admin")
def admin_key_revoke(kid):
    container().db.run("UPDATE api_key SET revoked_at=? WHERE id=?", (now_iso(), kid))
    return jsonify({"revoked": True})


@bp.get("/admin/users")
@auth_required("admin")
def admin_users():
    return jsonify({"users": container().users.list()})


@bp.post("/admin/users")
@auth_required("admin")
def admin_user_create():
    c, b = container(), body()
    if b.get("role") not in ("provider", "admin") or not b.get("email") or not b.get("name"):
        return err(400, "Enter a name, an email and a role (provider or admin).")
    if b["role"] == "provider" and not c.store.get(b.get("org_id") or ""):
        return err(400, "Choose the organization this provider account belongs to.")
    if c.settings.auth_mode == "cognito":  # pragma: no cover
        if c.users.by_email(b["email"]):
            return err(400, "An account with that email already exists.")
        c.auth.create_provider_login(b["email"], b["name"], b["role"], b.get("password"))
    u = c.users.create(b["email"], b["name"], b["role"],
                       b.get("password") if c.settings.auth_mode == "local" else None, b.get("org_id"))
    return jsonify(u), 201


@bp.get("/admin/documents")
@auth_required("admin")
def admin_docs():
    docs = container().documents.list(status=request.args.get("status") or None)
    return jsonify({"documents": docs})


@bp.post("/admin/documents")
@auth_required("admin")
def admin_upload():
    return _upload(True, request.form.get("org_id") or None)


@bp.post("/admin/documents/<did>/decide")
@auth_required("admin")
def admin_doc_decide(did):
    try:
        container().documents.decide(did, bool(body().get("approve")), g.principal.email)
    except ValueError as e:
        return err(422, str(e))
    return jsonify({"ok": True})


@bp.post("/admin/reindex")
@auth_required("admin")
def admin_reindex():
    return jsonify(container().jobs.start("reindex"))
