"""Loads a ready-to-demo environment: imports the generated data, creates demo users, policy documents,
help requests, API keys and an initial maintenance run."""
from __future__ import annotations
import json
from pathlib import Path

from app.db import dumps, new_id, now_iso
from app.services.users import AuthError
from app.web.routes_hsds import hash_key, new_api_key

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "data" / "generated"
CREDS = {"admin": ("admin@demo.org", "demo-admin-1"), "provider": ("provider1@demo.org", "demo-provider-1"),
         "seeker": ("ana@demo.org", "demo-seeker-1")}


def _org(c, name):
    rows, _ = c.store.list("organization", text_filter=name, limit=5)
    return next((r for r in rows if r["data"]["name"] == name), None)


def _service_of(c, org_id):
    rows, _ = c.store.list("service", org_id=org_id, limit=1)
    return rows[0] if rows else None


def _user(c, email, name, role, pw, org_id=None):
    return c.users.by_email(email) or c.users.create(email, name, role, pw, org_id)


def seed_demo(c, run_maintenance: bool = True) -> dict:
    out: dict = {"credentials": {}}
    if c.store.counts().get("service", 0) == 0:
        out["import"] = c.ingest_all("seed", "seed-demo")
    a = _user(c, *CREDS["admin"][:1], "Dana Admin", "admin", CREDS["admin"][1])
    out["credentials"]["admin"] = CREDS["admin"]
    demo_orgs = ["Bay Area Diaper Bank", "Tri-City Rent Relief", "Harbor Community Pantry", "Eastside Legal Aid", "Valley Family Health Clinic"]
    for i, n in enumerate(demo_orgs, 1):
        o = _org(c, n)
        if o:
            _user(c, f"provider{i}@demo.org", f"{n} staff", "provider", f"demo-provider-{i}", o["id"])
    out["credentials"]["provider"] = CREDS["provider"]
    seekers = [("ana@demo.org", "Ana Diaz", "94110", "I need diapers for my baby", True), ("marcus@demo.org", "Marcus Lee", "94609", "I need help paying rent", True),
               ("priya@demo.org", "Priya Nair", "95112", "Looking for a free food pantry", True), ("sam@demo.org", "Sam Ortiz", "94704", "Need legal help with an eviction notice", False),
               ("lena@demo.org", "Lena Park", "94063", "Looking for low-cost health care", True)]
    for email, name, zip_, need, share in seekers:
        u = _user(c, email, name, "seeker", "demo-seeker-1")
        c.seekers.save_profile(u["id"], {"zip": zip_, "household_size": 3, "language": "English", "needs": need, "share_with_providers": share,
                                         "contact_preference": "email"})
    out["credentials"]["seeker"] = CREDS["seeker"]
    # requests: one direct to the diaper bank (open), one unassigned, one already served
    if not c.db.one("SELECT 1 AS x FROM help_request LIMIT 1"):
        uid = lambda e: c.users.by_email(e)["id"]
        diaper = _org("Bay Area Diaper Bank") if False else _org(c, "Bay Area Diaper Bank")
        if diaper:
            s = _service_of(c, diaper["id"])
            c.seekers.create_request(uid("ana@demo.org"), "I need diapers for my baby", s["id"], 1.0)
            r = c.seekers.create_request(uid("priya@demo.org"), "free diapers and baby formula", None)
            r2 = c.seekers.create_request(uid("lena@demo.org"), "diapers for my toddler", s["id"], 1.0)
            c.seekers.respond(diaper["id"], r2["id"], "accept", "Pick up any weekday 9-4.")
        rent = _org(c, "Tri-City Rent Relief")
        if rent:
            c.seekers.create_request(uid("marcus@demo.org"), "I need help paying rent", _service_of(c, rent["id"])["id"], 1.0)
    # policy documents (approved) tied to organizations
    if not c.db.one("SELECT 1 AS x FROM document LIMIT 1") and (GEN / "policies" / "manifest.json").exists():
        for m in json.loads((GEN / "policies" / "manifest.json").read_text()):
            o = _org(c, m["organization"])
            if o:
                p = GEN / "policies" / m["file"]
                c.documents.upload(filename=p.name, data=p.read_bytes(), title=m["title"], uploaded_by="seed-demo", org_id=o["id"],
                                   effective_date=m["effective_date"], auto_approve=True)
    # API keys
    if not c.db.one("SELECT 1 AS x FROM api_key LIMIT 1"):
        for name, scope in (("Demo key (all sources)", None), ("Demo key (ODRS only)", "odrs")):
            key = new_api_key()
            c.db.run("INSERT INTO api_key (id,name,key_hash,key_prefix,source_scope,created_by,created_at) VALUES (?,?,?,?,?,?,?)",
                     (new_id(), name, hash_key(key), key[:8], scope, "seed-demo", now_iso()))
            out.setdefault("api_keys", {})[name] = key
    # user reports: demo the admin "reports" view. A report selects the record for the next run
    # and raises the `user_reported` flag for a specialist; the AI re-reviews only if the page
    # changed since the last review (it respects the hash-skip).
    if not c.db.one("SELECT 1 AS x FROM user_report LIMIT 1"):
        uid = lambda e: (c.users.by_email(e) or {}).get("id")
        demo_reports = [
            ("Bay Area Diaper Bank", "ana@demo.org", "The phone number on their site is different from what's listed here."),
            ("Harbor Community Pantry", "priya@demo.org", "I went and they were closed, the hours look wrong."),
            ("Tri-City Rent Relief", "marcus@demo.org", "This program may have moved."),
        ]
        for org_name, email, note in demo_reports:
            o = _org(c, org_name)
            svc = _service_of(c, o["id"]) if o else None
            u = c.users.by_email(email)
            if svc and u:
                c.maintenance.reports.file(svc["id"], reporter_id=u["id"], reporter_email=u["email"], note=note)
    if run_maintenance:
        out["maintenance"] = c.maintenance.run(scope="all", trigger="seed", initiated_by="seed-demo", force=True)
    return out
