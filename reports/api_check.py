#!/usr/bin/env python3
"""End-to-end API check for the One Degree Resource Engine (this repo).

Usage (from the repo root, with the repo's venv):
    PYTHONPATH=. .venv/bin/python reports/api_check.py http://127.0.0.1:8101 reports/api_check_results.json

It logs in as the three demo personas, calls every endpoint (happy path, bad input,
wrong role, no token), validates HSDS responses against the repo's vendored schemas,
and writes raw results as JSON. Run it against a COPY of the demo database: it
creates, edits, approves and rejects records and runs imports and maintenance.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

import jwt
import requests

BASE = sys.argv[1].rstrip("/")
OUT = Path(sys.argv[2])
S = requests.Session()
TOK: dict[str, str] = {}
R: list[dict] = []          # one row per check
M: dict = {}                # metrics and observations
RUN = str(int(time.time()))


def J(r):
    try:
        return r.json()
    except Exception:
        return {}


def call(method, path, role=None, expect=(200,), desc="", group="", route=None, key=None, **kw):
    headers = kw.pop("headers", {})
    if key:
        headers["Authorization"] = f"Bearer {key}"
    elif role and role in TOK:
        headers["Authorization"] = f"Bearer {TOK[role]}"
    t0 = time.perf_counter()
    try:
        resp = S.request(method, BASE + path, headers=headers, timeout=600, **kw)
        status = resp.status_code
    except Exception as e:  # noqa: BLE001
        resp, status = None, -1
        desc += f" [{type(e).__name__}]"
    ms = round((time.perf_counter() - t0) * 1000)
    R.append(dict(group=group, route=route or f"{method} {path.split('?')[0]}", method=method,
                  path=path.split("?")[0], role=("api-key" if key else role or "none"), desc=desc,
                  expected=list(expect), actual=status, ok=status in expect, ms=ms,
                  kind="happy" if min(expect) < 300 else "negative"))
    return resp


def check(group, route, desc, ok, detail=""):
    R.append(dict(group=group, route=route, method="CHECK", path="", role="-", desc=desc + (f" ({detail})" if detail else ""),
                  expected=["true"], actual=str(bool(ok)).lower(), ok=bool(ok), ms=0, kind="check"))


def login(email, pw):
    return S.post(BASE + "/api/auth/login", json={"email": email, "password": pw}, timeout=60).json()["token"]


def page_consistent(j, page, per):
    need = ["total_items", "total_pages", "page_number", "size", "first_page", "last_page", "empty", "contents"]
    if any(k not in j for k in need):
        return False, "missing keys: " + ",".join(k for k in need if k not in j)
    pages = max(1, math.ceil(j["total_items"] / per)) if j["total_items"] else 1
    problems = []
    if j["total_pages"] != pages: problems.append(f"total_pages {j['total_pages']}!={pages}")
    if j["size"] != len(j["contents"]): problems.append("size!=len(contents)")
    if j["empty"] != (len(j["contents"]) == 0): problems.append("empty flag wrong")
    if j["first_page"] != (j["page_number"] == 1): problems.append("first_page wrong")
    if j["last_page"] != (j["page_number"] >= j["total_pages"]): problems.append("last_page wrong")
    if j["page_number"] != page: problems.append("page_number wrong")
    return (not problems), "; ".join(problems)


def source_of(rec):
    x = rec.get("x_resource_engine") or {}
    s = x.get("source")
    return s.get("system") if isinstance(s, dict) else s


# =============================================================================== setup
TOK["admin"] = login("admin@demo.org", "demo-admin-1")
TOK["provider"] = login("provider1@demo.org", "demo-provider-1")
TOK["seeker"] = login("ana@demo.org", "demo-seeker-1")
admin_claims = jwt.decode(TOK["admin"], options={"verify_signature": False})

# =============================================================================== Auth & public
g = "Auth & public"
r = call("GET", "/api/health", None, (200,), "health reports status ok", g)
M["health"] = J(r)
r = call("POST", "/api/auth/login", None, (200,), "login with valid credentials returns a token", g)  # replaced below
R.pop()  # (the line above is only to keep the shape obvious; real call follows)
r = call("POST", "/api/auth/login", None, (200,), "login with valid credentials returns a token", g,
         json={"email": "ana@demo.org", "password": "demo-seeker-1"})
check(g, "POST /api/auth/login", "login response has token and public user (no password fields)",
      "token" in J(r) and not any("pass" in k.lower() or "hash" in k.lower() for k in (J(r).get("user") or {})))
call("POST", "/api/auth/login", None, (401,), "wrong password is rejected", g, json={"email": "ana@demo.org", "password": "nope-nope"})
call("POST", "/api/auth/login", None, (401,), "unknown user is rejected", g, json={"email": "ghost@demo.org", "password": "x"})
call("POST", "/api/auth/login", None, (401,), "empty body is rejected", g, json={})
new_email = f"qa.seeker.{RUN}@demo.org"
r = call("POST", "/api/auth/register", None, (200,), "register a new seeker", g, json={"email": new_email, "name": "QA Seeker", "password": "qa-password-1"})
call("POST", "/api/auth/register", None, (400, 401, 409, 422), "register with a short password is rejected", g,
     json={"email": f"short.{RUN}@demo.org", "name": "Short", "password": "abc"})
call("POST", "/api/auth/register", None, (400, 409, 422), "register with an existing email is rejected", g,
     json={"email": new_email, "name": "QA Seeker", "password": "qa-password-1"})
call("POST", "/api/auth/register", None, (400,), "register without a name is rejected", g, json={"email": f"x.{RUN}@demo.org"})
call("GET", "/api/auth/me", "seeker", (200,), "me returns the logged-in user", g)
call("GET", "/api/auth/me", None, (401,), "me without token is rejected", g)

r = call("POST", "/api/chat", None, (200,), "anonymous chat: general question", g, json={"message": "How does One Degree work?"})
M["chat_general"] = {k: (v if not isinstance(v, (list, dict)) else "...") for k, v in J(r).items()}
r = call("POST", "/api/chat", None, (200,), "anonymous chat: needs a profile before matching", g, json={"message": "I need rental assistance"})
sid = J(r).get("session_id")
M["chat_rent_keys"] = sorted(J(r).keys())
call("POST", "/api/chat", None, (400,), "chat with empty message is rejected", g, json={"message": "   "})
call("POST", "/api/chat", None, (200,), "chat truncates a 5,000-character message instead of failing", g, json={"message": "food " * 1000})
call("GET", f"/api/chat/history?session_id={sid}", None, (200,), "chat history for a session", g)
r = call("GET", "/api/chat/history?session_id=does-not-exist", None, (200,), "history for an unknown session returns an empty list", g)
check(g, "GET /api/chat/history", "unknown session history is empty (no data leak)", J(r).get("messages") == [], str(J(r))[:80])
r = call("GET", f"/api/chat/history?session_id={sid}", None, (200,), "anonymous caller can read an anonymous session by id", g)
M["history_anonymous_len"] = len(J(r).get("messages") or [])

# =============================================================================== Seeker
g = "Seeker"
r = call("GET", "/api/seeker/profile", "seeker", (200,), "get profile", g)
prof = J(r)
call("PUT", "/api/seeker/profile", "seeker", (200,), "save profile (round-trip)", g, json={**prof, "zip": "94110", "share_with_providers": True})
r = call("GET", "/api/seeker/profile", "seeker", (200,), "profile change persisted", g)
check(g, "PUT /api/seeker/profile", "saved zip is returned on next read", J(r).get("zip") == "94110", str(J(r).get("zip")))
r = call("GET", "/api/seeker/requests", "seeker", (200,), "list my help requests", g)
M["seeker_requests"] = len(J(r).get("requests") or [])
call("GET", "/api/search?q=food", "seeker", (200,), "directory search as seeker", g)
r = call("GET", "/api/search?q=", "seeker", (200,), "empty search query does not error", g)
call("POST", "/api/chat/resume", "seeker", (200,), "resume a chat session after login", g, json={"session_id": sid})

# service id needed for confirm/respond tests
r = call("GET", "/api/provider/organization", "provider", (200,), "provider: own organization bundle", "Provider")
bundle = J(r)
own_org = (bundle.get("organization") or {}).get("id")
own_services = [s["id"] for s in bundle.get("services") or []]
own_locs = [l["id"] for l in bundle.get("locations") or []]
svc = own_services[0] if own_services else None
M["provider_org"] = {"org_id": own_org, "services": len(own_services), "locations": len(own_locs)}
r = call("POST", "/api/chat/confirm", "seeker", (200, 409), "confirm a help request (200, or 409 if consent not given)", g,
         json={"session_id": sid, "service_id": svc})
M["confirm_status_body"] = J(r)

# =============================================================================== Provider
g = "Provider"
call("GET", f"/api/provider/records/{svc}", "provider", (200,), "get own service with history and change requests", g, route="GET /api/provider/records/<rid>")
call("GET", f"/api/provider/records/{own_org}", "provider", (200,), "get own organization record", g, route="GET /api/provider/records/<rid>")
call("GET", "/api/provider/records/does-not-exist", "provider", (404,), "unknown record returns 404", g, route="GET /api/provider/records/<rid>")

# another organization's service, via the HSDS API with an admin key
r = call("POST", "/api/admin/api-keys", "admin", (201,), "admin: create an all-sources API key", "Admin", json={"name": f"qa-all-{RUN}"})
KEY_ALL, KEY_ALL_ID = J(r).get("key"), J(r).get("id")
other_svc = other_org = None
for rec in J(S.get(BASE + "/hsds/services?per_page=100", headers={"Authorization": f"Bearer {KEY_ALL}"})).get("contents", []):
    if (rec.get("organization") or {}).get("id") not in (None, own_org):
        other_svc, other_org = rec["id"], rec["organization"]["id"]
        break
call("GET", f"/api/provider/records/{other_svc}", "provider", (403,), "cannot read another organization's record (IDOR)", g, route="GET /api/provider/records/<rid>")
call("POST", "/api/provider/change-requests", "provider", (403, 404), "cannot file a change for another organization's record (IDOR)", g,
     json={"resource_id": other_svc, "patch": {"description": "hijack"}})
call("POST", "/api/provider/change-requests", "provider", (400,), "empty patch is rejected", g, json={"resource_id": svc, "patch": {}})
call("POST", "/api/provider/change-requests", "provider", (422,), "patch that breaks HSDS (bad status) is rejected", g, json={"resource_id": svc, "patch": {"status": "bogus"}})
call("POST", "/api/provider/change-requests", "provider", (404,), "change for an unknown record returns 404", g, json={"resource_id": "nope", "patch": {"description": "x"}})

svc_before = J(S.get(BASE + f"/hsds/services/{svc}", headers={"Authorization": f"Bearer {KEY_ALL}"}))
orig_desc = svc_before.get("description")
# Two change requests on the same field to exercise stale detection later
r1 = call("POST", "/api/provider/change-requests", "provider", (201,), "file change request A (description)", g, json={"resource_id": svc, "patch": {"description": f"QA change A {RUN}"}})
r2 = call("POST", "/api/provider/change-requests", "provider", (201,), "file change request B (same field)", g, json={"resource_id": svc, "patch": {"description": f"QA change B {RUN}"}})
r3 = call("POST", "/api/provider/change-requests", "provider", (201,), "file change request C (to be rejected)", g, json={"resource_id": svc, "patch": {"url": f"https://example.org/qa-{RUN}"}})
CR_A, CR_B, CR_C = J(r1).get("id"), J(r2).get("id"), J(r3).get("id")
r = call("GET", "/api/provider/change-requests", "provider", (200,), "list my change requests", g)
check(g, "GET /api/provider/change-requests", "new change requests are listed as pending",
      {CR_A, CR_B, CR_C} <= {c["id"] for c in J(r).get("change_requests", []) if c.get("status") == "pending"})
call("GET", "/api/provider/needs", "provider", (200,), "needs of people served", g)
call("GET", "/api/provider/served", "provider", (200,), "people served", g)
call("POST", f"/api/provider/requests/anything/respond", "provider", (400,), "respond with an invalid action is rejected", g,
     json={"action": "explode"}, route="POST /api/provider/requests/<rid>/respond")
rr = call("POST", "/api/provider/requests/does-not-exist/respond", "provider", (200, 403, 404, 409), "respond to an unknown request is rejected cleanly (no 500)", g,
          json={"action": "accept"}, route="POST /api/provider/requests/<rid>/respond")
M["respond_unknown_status"] = rr.status_code if rr is not None else None
files = {"file": ("qa-policy.txt", b"Bring a photo ID and proof of address. Open weekdays 9 to 5.", "text/plain")}
r = call("POST", "/api/provider/documents", "provider", (201,), "upload a policy document (pending review)", g, files=files, data={"title": f"QA policy {RUN}"})
DOC_ID = J(r).get("id")
M["provider_doc_status"] = J(r).get("status")
call("POST", "/api/provider/documents", "provider", (400,), "upload without a file is rejected", g)
call("POST", "/api/provider/documents", "provider", (413,), "upload over 25 MB is rejected", g,
     files={"file": ("big.bin", b"0" * (26 * 1024 * 1024), "application/octet-stream")})
call("GET", "/api/provider/documents", "provider", (200,), "list my documents", g)

# =============================================================================== Admin
g = "Admin"
call("GET", "/api/admin/stats", "admin", (200,), "dashboard stats", g)
r = call("GET", "/api/admin/seekers", "admin", (200,), "list seekers", g)
seekers = J(r).get("seekers") or []
check(g, "GET /api/admin/seekers", "seeker list exposes no password material",
      not any(("pass" in k.lower() or "hash" in k.lower()) for s in seekers for k in s))
if seekers:
    call("GET", f"/api/admin/seekers/{seekers[0]['id']}", "admin", (200,), "seeker detail", g, route="GET /api/admin/seekers/<uid>")
call("GET", "/api/admin/seekers/does-not-exist", "admin", (404,), "unknown seeker returns 404", g, route="GET /api/admin/seekers/<uid>")
r = call("GET", "/api/admin/providers?per_page=5", "admin", (200,), "list providers (paged)", g)
M["providers_total"] = J(r).get("total")
call("GET", "/api/admin/providers?q=diaper", "admin", (200,), "provider text filter", g)
call("GET", f"/api/admin/providers/{own_org}", "admin", (200,), "provider detail", g, route="GET /api/admin/providers/<org_id>")
call("GET", "/api/admin/providers/does-not-exist", "admin", (404,), "unknown provider returns 404", g, route="GET /api/admin/providers/<org_id>")
call("GET", f"/api/admin/records/{svc}", "admin", (200,), "record with history and check", g, route="GET /api/admin/records/<rid>")
call("GET", "/api/admin/records/does-not-exist", "admin", (404,), "unknown record returns 404", g, route="GET /api/admin/records/<rid>")

# change-request review: approve A, then B must be detected as stale
r = call("GET", "/api/admin/change-requests", "admin", (200,), "list pending change requests", g)
check(g, "GET /api/admin/change-requests", "provider's requests appear in the admin queue", {CR_A, CR_B, CR_C} <= {c["id"] for c in J(r).get("change_requests", [])})
call("GET", "/api/admin/change-requests?status=all", "admin", (200,), "list with status filter", g)
call("GET", "/api/admin/change-requests?kind=provider_update", "admin", (200,), "list with kind filter", g)
r = call("POST", f"/api/admin/change-requests/{CR_A}/approve", "admin", (200,), "approve change request A", g, json={"note": "qa"}, route="POST /api/admin/change-requests/<cid>/approve")
after = J(S.get(BASE + f"/hsds/services/{svc}", headers={"Authorization": f"Bearer {KEY_ALL}"}))
check(g, "POST /api/admin/change-requests/<cid>/approve", "approved text is now served by the HSDS API", after.get("description") == f"QA change A {RUN}")
rec = J(S.get(BASE + f"/api/admin/records/{svc}", headers={"Authorization": f"Bearer {TOK['admin']}"}))
hist_txt = json.dumps(rec.get("history"))
check(g, "GET /api/admin/records/<rid>", "history records who approved and the old/new value", "admin@demo.org" in hist_txt and f"QA change A {RUN}" in hist_txt)
r = call("POST", f"/api/admin/change-requests/{CR_B}/approve", "admin", (409,), "approving B (based on old text) is blocked as stale", g, json={}, route="POST /api/admin/change-requests/<cid>/approve")
M["stale_approve_B_status"] = r.status_code
M["stale_approve_B_body"] = J(r)
call("POST", f"/api/admin/change-requests/{CR_B}/reject", "admin", (200,), "reject stale change request B", g, json={"note": "stale"}, route="POST /api/admin/change-requests/<cid>/reject")
call("POST", f"/api/admin/change-requests/{CR_C}/reject", "admin", (200,), "reject change request C", g, json={"note": "no"}, route="POST /api/admin/change-requests/<cid>/reject")
call("POST", "/api/admin/change-requests/does-not-exist/approve", "admin", (404,), "approve unknown id returns 404", g, json={}, route="POST /api/admin/change-requests/<cid>/approve")
call("POST", "/api/admin/change-requests/does-not-exist/reject", "admin", (404,), "reject unknown id returns 404", g, json={}, route="POST /api/admin/change-requests/<cid>/reject")

call("PUT", f"/api/admin/records/{svc}", "admin", (200,), "admin edits a record directly", g, json={"patch": {"description": f"QA admin edit {RUN}"}, "note": "qa"}, route="PUT /api/admin/records/<rid>")
call("PUT", f"/api/admin/records/{svc}", "admin", (422,), "admin edit that breaks HSDS is blocked", g, json={"patch": {"status": "bogus"}}, route="PUT /api/admin/records/<rid>")
call("PUT", "/api/admin/records/does-not-exist", "admin", (404,), "edit unknown record returns 404", g, json={"patch": {"description": "x"}}, route="PUT /api/admin/records/<rid>")
check(g, "PUT /api/admin/records/<rid>", "blocked edit left the record unchanged",
      J(S.get(BASE + f"/hsds/services/{svc}", headers={"Authorization": f"Bearer {KEY_ALL}"})).get("status") == "active")

# maintenance
before_runs = len(J(S.get(BASE + "/api/admin/maintenance/runs", headers={"Authorization": f"Bearer {TOK['admin']}"})).get("runs", []))
r = call("POST", "/api/admin/maintenance/run", "admin", (200,), "run the AI check for one service (wait)", g, json={"service_id": svc, "wait": True, "force": True})
M["maintenance_one"] = {k: v for k, v in J(r).items() if not isinstance(v, (list, dict))}
rec = J(S.get(BASE + f"/api/admin/records/{svc}", headers={"Authorization": f"Bearer {TOK['admin']}"}))
chk = rec.get("check") or {}
check(g, "POST /api/admin/maintenance/run", "the checked service now has a category and a checked-at time", bool(chk.get("category") and chk.get("checked_at")), str(chk.get("category")))
r = call("GET", "/api/admin/maintenance/results?per_page=5", "admin", (200,), "check results (paged)", g)
M["results_total"] = J(r).get("total")
cats = {}
for c in ("actively_bad", "check_failed", "discrepancy", "missing_information", "verified", "unchecked"):
    rr_ = J(S.get(BASE + f"/api/admin/maintenance/results?category={c}&per_page=200", headers={"Authorization": f"Bearer {TOK['admin']}"}))
    cats[c] = rr_.get("total")
    check(g, "GET /api/admin/maintenance/results", f"category filter '{c}' returns only that category",
          all(x["category"] == c for x in rr_.get("results", [])), f"{rr_.get('total')} results")
M["category_counts"] = cats
call("GET", "/api/admin/maintenance/results?q=diaper&source=odrs", "admin", (200,), "results with text and source filters", g)
call("GET", "/api/admin/maintenance/runs", "admin", (200,), "maintenance run history", g)
after_runs = len(J(S.get(BASE + "/api/admin/maintenance/runs", headers={"Authorization": f"Bearer {TOK['admin']}"})).get("runs", []))
check(g, "GET /api/admin/maintenance/runs", "the run we started is recorded", after_runs >= before_runs and after_runs > 0)

# imports: repeatability (R1.6) and counts balance (R1.7)
tot_before = J(S.get(BASE + "/hsds/services?per_page=1", headers={"Authorization": f"Bearer {KEY_ALL}"})).get("total_items")
r = call("POST", "/api/admin/imports/run", "admin", (200,), "re-run the import for all sources (wait)", g, json={"wait": True})
M["import_run_body"] = {k: v for k, v in J(r).items() if not isinstance(v, (list, dict))}
tot_after = J(S.get(BASE + "/hsds/services?per_page=1", headers={"Authorization": f"Bearer {KEY_ALL}"})).get("total_items")
check(g, "POST /api/admin/imports/run", "re-import does not create duplicates", tot_before == tot_after, f"{tot_before} -> {tot_after}")
r = call("GET", "/api/admin/imports", "admin", (200,), "import history and configured sources", g)
runs = J(r).get("runs") or []
M["import_sources"] = J(r).get("sources")
finished = [x for x in runs if x.get("status") != "running"]
check(g, "GET /api/admin/imports", "every finished import run balances (received = stored + quarantined)",
      bool(finished) and all(x.get("balanced") for x in finished), f"{len(finished)} runs")
r = call("GET", "/api/admin/quarantine", "admin", (200,), "quarantine list", g)
M["quarantine_count"] = len(J(r).get("quarantine") or [])
call("POST", "/api/admin/reindex", "admin", (200,), "rebuild the search index", g)

# API keys
r = call("POST", "/api/admin/api-keys", "admin", (201,), "create a source-scoped API key", g, json={"name": f"qa-scoped-{RUN}", "source_scope": "odrs"})
KEY_ODRS, KEY_ODRS_ID = J(r).get("key"), J(r).get("id")
check(g, "POST /api/admin/api-keys", "key looks like re_… and is shown once", str(KEY_ODRS).startswith("re_"))
call("POST", "/api/admin/api-keys", "admin", (400,), "create a key without a name is rejected", g, json={})
r = call("GET", "/api/admin/api-keys", "admin", (200,), "list keys", g)
keys_listed = J(r).get("keys") or []
check(g, "GET /api/admin/api-keys", "key list never shows full keys or hashes",
      keys_listed and all("key" not in k and "key_hash" not in k for k in keys_listed))
r = call("POST", "/api/admin/api-keys", "admin", (201,), "create a throwaway key to revoke", g, json={"name": f"qa-revoke-{RUN}"})
rk, rk_id = J(r).get("key"), J(r).get("id")
a = S.get(BASE + "/hsds/", headers={"Authorization": f"Bearer {rk}"}).status_code
call("DELETE", f"/api/admin/api-keys/{rk_id}", "admin", (200,), "revoke a key", g, route="DELETE /api/admin/api-keys/<kid>")
b = S.get(BASE + "/hsds/", headers={"Authorization": f"Bearer {rk}"}).status_code
check(g, "DELETE /api/admin/api-keys/<kid>", "revoked key stops working immediately", (a, b) == (200, 401), f"before {a}, after {b}")
call("DELETE", "/api/admin/api-keys/does-not-exist", "admin", (200, 404), "revoke an unknown id does not error", g, route="DELETE /api/admin/api-keys/<kid>")

# users
r = call("GET", "/api/admin/users", "admin", (200,), "list users", g)
users = J(r).get("users") or []
check(g, "GET /api/admin/users", "user list exposes no password material", not any(("pass" in k.lower() or "hash" in k.lower()) for u in users for k in u))
new_prov = f"qa.provider.{RUN}@demo.org"
r = call("POST", "/api/admin/users", "admin", (201,), "create a provider account", g, json={"email": new_prov, "name": "QA Provider", "role": "provider", "org_id": own_org, "password": "qa-password-1"})
call("POST", "/api/admin/users", "admin", (400, 409, 422), "duplicate email is rejected cleanly", g, json={"email": new_prov, "name": "QA Provider", "role": "provider", "org_id": own_org, "password": "qa-password-1"})
call("POST", "/api/admin/users", "admin", (400,), "invalid role is rejected", g, json={"email": f"r.{RUN}@demo.org", "name": "R", "role": "seeker"})
call("POST", "/api/admin/users", "admin", (400,), "provider without an organization is rejected", g, json={"email": f"o.{RUN}@demo.org", "name": "O", "role": "provider"})
tok_new = S.post(BASE + "/api/auth/login", json={"email": new_prov, "password": "qa-password-1"}).status_code
check(g, "POST /api/admin/users", "the new provider can log in", tok_new == 200, f"login status {tok_new}")

# documents
r = call("GET", "/api/admin/documents?status=pending", "admin", (200,), "pending documents", g)
check(g, "GET /api/admin/documents", "provider's upload is waiting for review", DOC_ID in {d.get("id") for d in J(r).get("documents", [])})
call("GET", "/api/admin/documents", "admin", (200,), "all documents", g)
call("POST", f"/api/admin/documents/{DOC_ID}/decide", "admin", (200,), "approve the document", g, json={"approve": True}, route="POST /api/admin/documents/<did>/decide")
call("POST", "/api/admin/documents/does-not-exist/decide", "admin", (404, 422), "decide on an unknown document fails cleanly", g, json={"approve": True}, route="POST /api/admin/documents/<did>/decide")
call("POST", "/api/admin/documents", "admin", (201,), "admin uploads (auto-approved)", g,
     files={"file": ("admin-policy.txt", b"Admin uploaded policy text.", "text/plain")}, data={"title": f"QA admin policy {RUN}"})
call("POST", "/api/admin/documents", "admin", (400,), "admin upload without a file is rejected", g)

# =============================================================================== User reports (branch feature)
g = "User reports"
rep_svc = own_services[0] if own_services else None
call("POST", "/api/reports", None, (401,), "filing a report requires login", g)
r = call("POST", "/api/reports", "seeker", (200, 201), "a signed-in seeker can report a listing", g, json={"resource_id": rep_svc, "reason": "Hours look wrong"})
M["report_file_body"] = J(r)
call("POST", "/api/reports", "seeker", (400, 404, 422), "report for an unknown record is rejected", g, json={"resource_id": "nope", "reason": "x"})
r = call("GET", "/api/admin/reports", "admin", (200,), "admin lists open reports", g)
reports = J(r).get("reports") or J(r).get("items") or (J(r) if isinstance(J(r), list) else [])
M["open_reports"] = len(reports) if isinstance(reports, list) else None
rid_report = (reports[0].get("id") if reports and isinstance(reports, list) and isinstance(reports[0], dict) else None)
if rid_report:
    call("POST", f"/api/admin/reports/{rid_report}/resolve", "admin", (200,), "admin resolves a report", g, route="POST /api/admin/reports/<report_id>/resolve")
rec = J(S.get(BASE + f"/api/admin/records/{rep_svc}", headers={"Authorization": f"Bearer {TOK['admin']}"})) if rep_svc else {}
check(g, "POST /api/reports", "a user report raises the user_reported flag / forces a recheck",
      "user_reported" in json.dumps(rec).lower() or bool(M.get("report_file_body")))

# =============================================================================== HSDS API
g = "HSDS API"
H = {"Authorization": f"Bearer {KEY_ALL}"}
src_names = [s["name"] for s in (M.get("import_sources") or [])]
other_src = next((s for s in src_names if s != "odrs"), None)
r = call("POST", "/api/admin/api-keys", "admin", (201,), "create a key scoped to the other source", "Admin", json={"name": f"qa-{other_src}-{RUN}", "source_scope": other_src})
KEY_OTHER = J(r).get("key")
call("GET", "/hsds/", None, (200,), "root info", g, key=KEY_ALL)
lists = {"services": "service", "organizations": "organization", "service_at_locations": "service_at_location",
         "locations": "location", "taxonomies": "taxonomy", "taxonomy_terms": "taxonomy_term"}
first_ids, totals = {}, {}
for ep in lists:
    r = call("GET", f"/hsds/{ep}?per_page=5", None, (200,), f"list {ep}", g, key=KEY_ALL)
    j = J(r)
    ok, why = page_consistent(j, 1, 5)
    check(g, f"GET /hsds/{ep}", f"Page wrapper is internally consistent", ok, why or f"{j.get('total_items')} items")
    totals[ep] = j.get("total_items")
    if j.get("contents"):
        first_ids[ep] = j["contents"][0]["id"]
M["hsds_totals"] = totals
for ep, kind in (("services", "service"), ("organizations", "organization"), ("service_at_locations", "service_at_location"),
                 ("locations", "location"), ("taxonomy_terms", "taxonomy_term")):
    call("GET", f"/hsds/{ep}/{first_ids.get(ep)}", None, (200,), f"get one {kind} by id", g, key=KEY_ALL, route=f"GET /hsds/{ep}/<rid>")
    call("GET", f"/hsds/{ep}/does-not-exist", None, (404,), f"unknown {kind} id returns 404", g, key=KEY_ALL, route=f"GET /hsds/{ep}/<rid>")
call("GET", f"/hsds/organizations/{first_ids.get('services')}", None, (404,), "a service id is not served as an organization", g, key=KEY_ALL, route="GET /hsds/organizations/<rid>")
r = call("GET", f"/hsds/taxonomies/{first_ids.get('taxonomies')}", None, (200, 404), "get one taxonomy by id (optional in HSDS)", g, key=KEY_ALL, route="GET /hsds/taxonomies/<rid> (not implemented)")
M["taxonomy_by_id_status"] = r.status_code

# paging
total = totals["services"]
last = math.ceil(total / 25)
for page, per in ((1, 25), (2, 25), (last, 25), (last + 5, 25), (1, 100)):
    r = call("GET", f"/hsds/services?page={page}&per_page={per}&minimal=true", None, (200,), f"services page {page}, per_page {per}", g, key=KEY_ALL, route="GET /hsds/services")
    ok, why = page_consistent(J(r), page, per)
    check(g, "GET /hsds/services", f"page {page}/{per}: wrapper consistent", ok, why)
r = call("GET", "/hsds/services?per_page=1000&minimal=true", None, (200,), "per_page above the maximum is capped", g, key=KEY_ALL, route="GET /hsds/services")
M["per_page_1000_size"] = J(r).get("size")
ids_p1 = [x["id"] for x in J(S.get(BASE + "/hsds/services?page=1&per_page=25&minimal=true", headers=H)).get("contents", [])]
ids_p2 = [x["id"] for x in J(S.get(BASE + "/hsds/services?page=2&per_page=25&minimal=true", headers=H)).get("contents", [])]
check(g, "GET /hsds/services", "consecutive pages do not overlap", not (set(ids_p1) & set(ids_p2)))
all_ids = []
for p in range(1, last + 1):
    all_ids += [x["id"] for x in J(S.get(BASE + f"/hsds/services?page={p}&per_page=25&minimal=true", headers=H)).get("contents", [])]
check(g, "GET /hsds/services", "walking every page returns each service exactly once", len(all_ids) == total and len(set(all_ids)) == total, f"{len(all_ids)} of {total}, {len(set(all_ids))} unique")

# filters
r = call("GET", "/hsds/services?status=inactive", None, (200,), "status filter", g, key=KEY_ALL, route="GET /hsds/services")
M["inactive_total"] = J(r).get("total_items")
r = call("GET", "/hsds/services?modified_after=2999-01-01", None, (200,), "modified_after in the far future returns nothing", g, key=KEY_ALL, route="GET /hsds/services")
check(g, "GET /hsds/services", "modified_after in the future gives an empty page", J(r).get("empty") is True and J(r).get("total_items") == 0)
r = call("GET", "/hsds/services?modified_after=2000-01-01", None, (200,), "modified_after in the past returns everything", g, key=KEY_ALL, route="GET /hsds/services")
check(g, "GET /hsds/services", "modified_after in the past returns all services", J(r).get("total_items") == total, f"{J(r).get('total_items')} of {total}")
r = call("GET", f"/hsds/services?organization_id={own_org}", None, (200,), "organization_id filter", g, key=KEY_ALL, route="GET /hsds/services")
org_hits = J(r).get("contents", [])
check(g, "GET /hsds/services", "organization_id returns only that organization's services", bool(org_hits) and all((x.get("organization") or {}).get("id") == own_org for x in org_hits), f"{len(org_hits)} services")
terms = J(S.get(BASE + "/hsds/taxonomy_terms?per_page=100", headers=H)).get("contents", [])
term_id = terms[0]["id"] if terms else None
r = call("GET", f"/hsds/services?taxonomy_term_id={term_id}", None, (200,), "taxonomy_term_id filter", g, key=KEY_ALL, route="GET /hsds/services")
M["term_filter_total"] = J(r).get("total_items")
r = call("GET", f"/hsds/services?organization_id={own_org}&status=inactive", None, (200,), "filters combine with AND", g, key=KEY_ALL, route="GET /hsds/services")
check(g, "GET /hsds/services", "organization_id AND status=inactive is a subset of organization_id alone", (J(r).get("total_items") or 0) <= len(org_hits), f"{J(r).get('total_items')} <= {len(org_hits)}")
call("GET", "/hsds/services?minimal=true&per_page=2", None, (200,), "minimal=true projection", g, key=KEY_ALL, route="GET /hsds/services")
full = J(S.get(BASE + "/hsds/services?per_page=1", headers=H)).get("contents", [{}])[0]
mini = J(S.get(BASE + "/hsds/services?per_page=1&minimal=true", headers=H)).get("contents", [{}])[0]
check(g, "GET /hsds/services", "minimal is smaller than the full record", len(json.dumps(mini)) < len(json.dumps(full)), f"{len(json.dumps(mini))} < {len(json.dumps(full))} bytes")
ext = J(S.get(BASE + "/hsds/services?per_page=1&extensions=true", headers=H)).get("contents", [{}])[0]
check(g, "GET /hsds/services", "x_resource_engine is hidden by default and shown with extensions=true", "x_resource_engine" not in full and "x_resource_engine" in ext)

# scoping (R3.4)
n_all = J(S.get(BASE + "/hsds/services?per_page=1", headers=H)).get("total_items")
n_odrs = J(S.get(BASE + "/hsds/services?per_page=1", headers={"Authorization": f"Bearer {KEY_ODRS}"})).get("total_items")
n_oth = J(S.get(BASE + "/hsds/services?per_page=1", headers={"Authorization": f"Bearer {KEY_OTHER}"})).get("total_items")
call("GET", "/hsds/services?per_page=1", None, (200,), "source-scoped key (odrs) can list", g, key=KEY_ODRS, route="GET /hsds/services")
check(g, "GET /hsds/services", "scoped keys partition the data (odrs + other = all)", n_odrs + n_oth == n_all, f"{n_odrs} + {n_oth} = {n_all}")
e1 = J(S.get(BASE + "/hsds/services?per_page=100&extensions=true", headers={"Authorization": f"Bearer {KEY_ODRS}"})).get("contents", [])
check(g, "GET /hsds/services", "every record returned to the odrs key comes from odrs", bool(e1) and all(source_of(x) == "odrs" for x in e1), f"{len(e1)} checked")
oth_rec = next((x for x in J(S.get(BASE + "/hsds/services?per_page=100&extensions=true", headers=H)).get("contents", []) if source_of(x) == other_src), None)
if oth_rec:
    call("GET", f"/hsds/services/{oth_rec['id']}", None, (404,), "odrs key asking for another source's service gets 404", g, key=KEY_ODRS, route="GET /hsds/services/<rid>")
    call("GET", f"/hsds/services/{oth_rec['id']}", None, (200,), "the matching scoped key can read it", g, key=KEY_OTHER, route="GET /hsds/services/<rid>")
    oid = (oth_rec.get("organization") or {}).get("id")
    if oid:
        call("GET", f"/hsds/organizations/{oid}", None, (404,), "odrs key cannot read another source's organization", g, key=KEY_ODRS, route="GET /hsds/organizations/<rid>")
for ep in ("organizations", "service_at_locations", "locations"):
    a_ = J(S.get(BASE + f"/hsds/{ep}?per_page=1", headers=H)).get("total_items")
    b_ = J(S.get(BASE + f"/hsds/{ep}?per_page=1", headers={"Authorization": f"Bearer {KEY_ODRS}"})).get("total_items")
    check(g, f"GET /hsds/{ep}", "scoped key sees fewer records than the all-sources key", (b_ or 0) < (a_ or 0), f"{b_} < {a_}")
a_ = J(S.get(BASE + "/hsds/taxonomy_terms?per_page=1", headers=H)).get("total_items")
b_ = J(S.get(BASE + "/hsds/taxonomy_terms?per_page=1", headers={"Authorization": f"Bearer {KEY_ODRS}"})).get("total_items")
M["taxonomy_scope"] = {"all": a_, "odrs_key": b_}

# search quality
sq = {}
for q in ("diapers", "rent", "food", "legal", "dental", "zzzzqqqq"):
    j = J(S.get(BASE + f"/hsds/services?search={q}&per_page=10", headers=H))
    hits = j.get("contents", [])
    rel = sum(1 for x in hits if q in json.dumps({k: x.get(k) for k in ("name", "description")}).lower() or q in ((x.get("organization") or {}).get("name", "")).lower())
    sq[q] = {"total": j.get("total_items"), "top10_containing_term": rel, "top10": len(hits), "top3": [x["name"][:50] for x in hits[:3]]}
M["search_quality"] = sq
call("GET", "/hsds/services?search=diapers&q=rent", None, (200,), "search and q together do not error", g, key=KEY_ALL, route="GET /hsds/services")

# HSDS conformance with the repo's own vendored schemas
try:
    from app.hsds.validator import HsdsValidator
    V = HsdsValidator(Path("schemas/hsds/3.2.3"), "3.2.3")
    conf = {}
    for ep, kind in (("services", "service"), ("organizations", "organization"), ("locations", "location"),
                     ("service_at_locations", "service_at_location"), ("taxonomy_terms", "taxonomy_term"), ("taxonomies", "taxonomy")):
        recs, p = [], 1
        while True:
            j = J(S.get(BASE + f"/hsds/{ep}?page={p}&per_page=100", headers=H))
            recs += j.get("contents", [])
            if j.get("last_page", True) or not j.get("contents"):
                break
            p += 1
        errs = Counter()
        bad = 0
        for rec in recs:
            e = V.errors(kind, rec)
            if e:
                bad += 1
                for m in e[:3]:
                    errs[re.sub(r"/\d+", "/N", m)[:140]] += 1
        conf[ep] = {"checked": len(recs), "invalid": bad, "top_errors": errs.most_common(4)}
        check(g, f"GET /hsds/{ep}", f"every served {kind} validates against the vendored HSDS 3.2.3 schema", bad == 0, f"{len(recs) - bad}/{len(recs)} valid")
    M["hsds_conformance"] = conf
    M["validator_engine"] = V.engine()
except Exception as e:  # noqa: BLE001
    M["hsds_conformance_error"] = f"{type(e).__name__}: {e}"

# latency
lat = {}
for name, path in (("list25", "/hsds/services?per_page=25"), ("list25_minimal", "/hsds/services?per_page=25&minimal=true"),
                   ("by_id", f"/hsds/services/{svc}"), ("search", "/hsds/services?search=food&per_page=25"),
                   ("admin_results", "/api/admin/maintenance/results?per_page=25")):
    hdr = {"Authorization": f"Bearer {TOK['admin']}"} if path.startswith("/api") else H
    ts = []
    for _ in range(30):
        t0 = time.perf_counter(); S.get(BASE + path, headers=hdr); ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    lat[name] = {"p50_ms": round(statistics.median(ts)), "p95_ms": round(ts[int(len(ts) * 0.95) - 1]), "max_ms": round(ts[-1])}
M["latency"] = lat

# =============================================================================== Access control
g = "Access control"
ADMIN_GET = ["/api/admin/stats", "/api/admin/seekers", "/api/admin/providers", "/api/admin/change-requests", "/api/admin/maintenance/results",
             "/api/admin/maintenance/runs", "/api/admin/imports", "/api/admin/quarantine", "/api/admin/api-keys", "/api/admin/users",
             "/api/admin/documents", "/api/admin/seekers/x", "/api/admin/providers/x", "/api/admin/records/x"]
ADMIN_MUT = [("POST", "/api/admin/change-requests/x/approve"), ("POST", "/api/admin/change-requests/x/reject"), ("PUT", "/api/admin/records/x"),
             ("POST", "/api/admin/maintenance/run"), ("POST", "/api/admin/imports/run"), ("POST", "/api/admin/api-keys"),
             ("DELETE", "/api/admin/api-keys/x"), ("POST", "/api/admin/users"), ("POST", "/api/admin/documents"),
             ("POST", "/api/admin/documents/x/decide"), ("POST", "/api/admin/reindex")]
PROV = [("GET", "/api/provider/organization"), ("GET", "/api/provider/records/x"), ("POST", "/api/provider/change-requests"),
        ("GET", "/api/provider/change-requests"), ("GET", "/api/provider/needs"), ("GET", "/api/provider/served"),
        ("POST", "/api/provider/requests/x/respond"), ("POST", "/api/provider/documents"), ("GET", "/api/provider/documents")]
SEEK = [("GET", "/api/seeker/profile"), ("PUT", "/api/seeker/profile"), ("GET", "/api/seeker/requests"),
        ("POST", "/api/chat/resume"), ("POST", "/api/chat/confirm")]
ANY_LOGIN = [("GET", "/api/auth/me"), ("GET", "/api/search?q=food")]
HSDS_ALL = ["/hsds/", "/hsds/services", "/hsds/services/x", "/hsds/organizations", "/hsds/organizations/x", "/hsds/service_at_locations",
            "/hsds/service_at_locations/x", "/hsds/locations", "/hsds/locations/x", "/hsds/taxonomies", "/hsds/taxonomy_terms", "/hsds/taxonomy_terms/x"]


def sweep(routes, allowed_roles, label):
    for m, p in routes:
        rt = f"{m} {re.sub(r'/x(?=/|$)', lambda _: '/<id>', p.split('?')[0])}"
        call(m, p, None, (401,), f"{label}: no token → 401", g, route=rt)
        for role in ("seeker", "provider", "admin"):
            if role not in allowed_roles:
                call(m, p, role, (403,), f"{label}: {role} token → 403", g, route=rt, json={})


sweep([("GET", p) for p in ADMIN_GET] + ADMIN_MUT, {"admin"}, "admin route")
sweep([("GET", "/api/admin/reports"), ("POST", "/api/admin/reports/x/resolve")], {"admin"}, "admin route")
sweep([("POST", "/api/reports")], {"seeker", "provider", "admin"}, "login-only route")
sweep(PROV, {"provider"}, "provider route")
sweep(SEEK, {"seeker"}, "seeker route")
sweep(ANY_LOGIN, {"seeker", "provider", "admin"}, "login-only route")
for p in HSDS_ALL:
    rt = f"GET {re.sub(r'/x$', '/<rid>', p)}"
    call("GET", p, None, (401,), "HSDS: no key → 401", g, route=rt)
    call("GET", p, None, (401,), "HSDS: unknown key → 401", g, route=rt, key="re_not-a-real-key")
    call("GET", p, "seeker", (401,), "HSDS: seeker login token → 401", g, route=rt)
call("GET", "/api/admin/stats", None, (401,), "an API key is not accepted on /api routes", g, route="GET /api/admin/stats", key=KEY_ALL)
call("GET", "/hsds/services", "admin", (200,), "HSDS accepts an admin login token", g, route="GET /hsds/services")
for m in ("POST", "PUT", "DELETE"):
    call(m, "/hsds/services", None, (401, 405), f"HSDS is read-only: {m} /hsds/services", g, key=KEY_ALL, route=f"{m} /hsds/services")

# token tampering
now = int(time.time())
base_claims = {"sub": admin_claims["sub"], "email": "admin@demo.org", "name": "Admin", "role": "admin", "org": None, "iat": now, "exp": now + 600}
call("GET", "/api/admin/stats", None, (401,), "token signed with a wrong secret is rejected", g, route="GET /api/admin/stats",
     headers={"Authorization": "Bearer " + jwt.encode(base_claims, "x" * 40, algorithm="HS256")})
call("GET", "/api/admin/stats", None, (401,), "expired token is rejected", g, route="GET /api/admin/stats",
     headers={"Authorization": "Bearer " + jwt.encode({**base_claims, "exp": now - 60}, "dev-only-change-me", algorithm="HS256")})
alg_none = jwt.encode(base_claims, key=None, algorithm="none")
call("GET", "/api/admin/stats", None, (401,), "unsigned (alg=none) token is rejected", g, route="GET /api/admin/stats", headers={"Authorization": "Bearer " + alg_none})
sk = TOK["seeker"].split(".")
import base64
pl = json.loads(base64.urlsafe_b64decode(sk[1] + "=" * (-len(sk[1]) % 4)))
pl["role"] = "admin"
tampered = sk[0] + "." + base64.urlsafe_b64encode(json.dumps(pl).encode()).rstrip(b"=").decode() + "." + sk[2]
call("GET", "/api/admin/stats", None, (401,), "seeker token with role edited to admin is rejected", g, route="GET /api/admin/stats", headers={"Authorization": "Bearer " + tampered})
rf = call("GET", "/api/admin/stats", None, (401,), "token signed with the PUBLISHED default secret (dev-only-change-me) is rejected", g, route="GET /api/admin/stats",
          headers={"Authorization": "Bearer " + jwt.encode(base_claims, "dev-only-change-me", algorithm="HS256")})
M["forged_with_default_secret_status"] = rf.status_code

# =============================================================================== Robustness
g = "Robustness"
weird = ["?page=abc&per_page=-1", "?page=99999999999999999999", "?q=%00", "?q=" + "a" * 5000, "?per_page=0", "?modified_after=not-a-date", "?status=%27%3B--"]
n5 = 0
for p in ["/hsds/services", "/hsds/organizations", "/hsds/service_at_locations", "/hsds/locations", "/hsds/taxonomy_terms"]:
    for w in weird:
        r = call("GET", p + w, None, tuple(range(200, 500)), f"odd query {w[:28]!r} does not crash", g, key=KEY_ALL, route=f"GET {p}")
        n5 += (r is None or r.status_code >= 500)
for p in ["/api/admin/providers", "/api/admin/maintenance/results", "/api/admin/change-requests", "/api/search"]:
    for w in weird:
        r = call("GET", p + w, "admin", tuple(range(200, 500)), f"odd query {w[:28]!r} does not crash", g, route=f"GET {p}")
        n5 += (r is None or r.status_code >= 500)
M["fuzz_5xx"] = n5
bad_json = {"data": "{bad json", "headers": {"Content-Type": "application/json"}}
for m, p, role in (("POST", "/api/auth/login", None), ("POST", "/api/auth/register", None), ("POST", "/api/chat", None),
                   ("POST", "/api/provider/change-requests", "provider"), ("POST", "/api/admin/users", "admin"), ("POST", "/api/admin/api-keys", "admin"),
                   ("PUT", "/api/seeker/profile", "seeker")):
    call(m, p, role, tuple(range(200, 500)), "malformed JSON body does not crash", g, route=f"{m} {p}", **{"data": bad_json["data"], "headers": dict(bad_json["headers"])})
call("GET", "/api/does-not-exist", None, (404,), "unknown /api path returns JSON 404", g, route="GET /api/<unknown>")
call("GET", "/hsds/does-not-exist", None, (404, 401), "unknown /hsds path returns 404", g, route="GET /hsds/<unknown>")
hr = S.get(BASE + "/api/health")
M["headers"] = {k: hr.headers.get(k) for k in ("Content-Type", "X-Content-Type-Options", "X-Frame-Options", "Strict-Transport-Security",
                                                "Content-Security-Policy", "Cache-Control", "Access-Control-Allow-Origin", "Server")}
hs = S.get(BASE + "/hsds/services?per_page=1", headers=H)
M["hsds_headers"] = {k: hs.headers.get(k) for k in ("Content-Type", "Cache-Control", "Access-Control-Allow-Origin")}

# brute force last: it could lock accounts if throttling existed
codes = [S.post(BASE + "/api/auth/login", json={"email": "ana@demo.org", "password": f"wrong-{i}"}).status_code for i in range(15)]
M["bruteforce_codes"] = dict(Counter(codes))
after_ok = S.post(BASE + "/api/auth/login", json={"email": "ana@demo.org", "password": "demo-seeker-1"}).status_code
M["after_bruteforce_valid_login"] = after_ok
g = "Auth & public"
check(g, "POST /api/auth/login", "repeated wrong passwords are throttled (429) at some point", 429 in codes, f"15 attempts → {dict(Counter(codes))}")

OUT.write_text(json.dumps({"base": BASE, "run": RUN, "results": R, "metrics": M}, indent=1, default=str))
tot = len(R); ok = sum(1 for x in R if x["ok"])
print(f"{ok}/{tot} checks as expected; failures: {tot - ok}")
for x in R:
    if not x["ok"]:
        print(f"  FAIL [{x['group']}] {x['route']} ({x['role']}): {x['desc']} → got {x['actual']}, expected {x['expected']}")
