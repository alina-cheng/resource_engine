"""HSDS REST API (priority 3 + search). Bearer API key required on every endpoint (not an open API).
A key can be scoped to one source so a caller sees only that source's records (R3.4)."""
from __future__ import annotations
import hashlib
import math
import secrets
from functools import wraps

from flask import Blueprint, g, jsonify, request

from app.db import now_iso
from app.hsds.nest import Views
from app.services.users import AuthError
from app.web import container, current_principal, err

bp = Blueprint("hsds", __name__)
MAX_PER_PAGE = 100


def hash_key(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()


def new_api_key() -> str:
    return "re_" + secrets.token_urlsafe(32)


def api_key_required(fn):
    @wraps(fn)
    def w(*a, **kw):
        h = request.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            return err(401, "Send an API key as 'Authorization: Bearer <key>'.")
        tok, c = h[7:], container()
        g.scope = None
        if tok.startswith("re_"):
            row = c.db.one("SELECT * FROM api_key WHERE key_hash=? AND revoked_at IS NULL", (hash_key(tok),))
            if not row:
                return err(401, "That API key is not valid.")
            c.db.run("UPDATE api_key SET last_used_at=? WHERE id=?", (now_iso(), row["id"]))
            g.scope = row["source_scope"]
        else:                                           # admins may also browse with their login token
            p = current_principal()
            if not p or p.role != "admin":
                return err(401, "That token is not valid for the HSDS API.")
        return fn(*a, **kw)
    return w


def paging():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per = min(MAX_PER_PAGE, max(1, int(request.args.get("per_page", 25))))
    except ValueError:
        page, per = 1, 25
    return page, per


def page_response(contents: list, total: int, page: int, per: int):
    pages = max(1, math.ceil(total / per)) if total else 1
    return jsonify({"total_items": total, "total_pages": pages, "page_number": page, "size": len(contents),
                    "first_page": page == 1, "last_page": page >= pages, "empty": not contents, "contents": contents})


def _ext() -> bool:
    return request.args.get("extensions", "").lower() == "true"


@bp.get("/")
@api_key_required
def root():
    c = container()
    return jsonify({"profile": "https://docs.openreferral.org/en/latest/hsds/", "version": c.settings.hsds_version,
                    "openapi_url": "https://raw.githubusercontent.com/openreferral/specification/3.2/schema/openapi.json",
                    "publisher": {"name": "One Degree Resource Engine"},
                    "data_guide": "Records are HSDS JSON. Pass ?extensions=true to include x_resource_engine metadata."})


@bp.get("/services")
@api_key_required
def services():
    c, page, per = container(), *paging()
    a = request.args
    ids = None
    search = a.get("search") or a.get("q")
    if search:
        hits = c.search.search_services(search, filters={"status": "active"} if a.get("status", "active") == "active" else None, limit=500)
        ids = [h["id"] for h in hits]
        order = {h["id"]: i for i, h in enumerate(hits)}
    rows, total = c.store.list("service", org_id=a.get("organization_id"), source=g.scope, status=a.get("status"),
                               modified_after=a.get("modified_after"), term_id=a.get("taxonomy_term_id"),
                               taxonomy_id=a.get("taxonomy_id"), ids=ids, limit=per if not search else 1000,
                               offset=(page - 1) * per if not search else 0)
    if search:
        rows.sort(key=lambda r: order.get(r["id"], 1e9))
        total = len(rows)
        rows = rows[(page - 1) * per: page * per]
    v = Views(c.store)
    minimal = a.get("minimal", "").lower() == "true"
    if not minimal:
        v.prefetch(rows)
    return page_response([v.service(r, minimal=minimal, ext=_ext()) for r in rows], total, page, per)


def _one(rtype, builder):
    c = container()

    def run(rid):
        row = c.store.get(rid)
        if not row or row["type"] != rtype or (g.scope and row["source"] != g.scope):
            return err(404, "Not found.")
        v = Views(c.store)
        if rtype == "service":
            v.prefetch([row])
        return jsonify(builder(v, row))
    return run


@bp.get("/services/<rid>")
@api_key_required
def service_one(rid):
    return _one("service", lambda v, r: v.service(r, ext=_ext()))(rid)


@bp.get("/organizations")
@api_key_required
def organizations():
    c, page, per = container(), *paging()
    rows, total = c.store.list("organization", source=g.scope, modified_after=request.args.get("modified_after"), limit=per, offset=(page - 1) * per)
    v = Views(c.store)
    minimal = request.args.get("minimal", "").lower() == "true"
    return page_response([v.organization(r, minimal=True if minimal else False, ext=_ext()) for r in rows], total, page, per)


@bp.get("/organizations/<rid>")
@api_key_required
def organization_one(rid):
    return _one("organization", lambda v, r: v.organization(r, ext=_ext()))(rid)


@bp.get("/service_at_locations")
@api_key_required
def sals():
    c, page, per = container(), *paging()
    rows, total = c.store.list("service_at_location", source=g.scope, limit=per, offset=(page - 1) * per)
    v = Views(c.store)
    return page_response([v.service_at_location(r, ext=_ext()) for r in rows], total, page, per)


@bp.get("/service_at_locations/<rid>")
@api_key_required
def sal_one(rid):
    return _one("service_at_location", lambda v, r: v.service_at_location(r, ext=_ext()))(rid)


@bp.get("/locations")
@api_key_required
def locations():
    c, page, per = container(), *paging()
    rows, total = c.store.list("location", source=g.scope, limit=per, offset=(page - 1) * per)
    return page_response([Views(c.store).location(r, ext=_ext()) for r in rows], total, page, per)


@bp.get("/locations/<rid>")
@api_key_required
def location_one(rid):
    return _one("location", lambda v, r: v.location(r, ext=_ext()))(rid)


@bp.get("/taxonomies")
@api_key_required
def taxonomies():
    c, page, per = container(), *paging()
    rows, total = c.store.list("taxonomy", limit=per, offset=(page - 1) * per)
    return page_response([r["data"] for r in rows], total, page, per)


@bp.get("/taxonomy_terms")
@api_key_required
def terms():
    c, page, per = container(), *paging()
    rows, total = c.store.list("taxonomy_term", limit=per, offset=(page - 1) * per,
                               text_filter=None)
    v = Views(c.store)
    tax = request.args.get("taxonomy_id")
    out = [v.taxonomy_term(r, ext=_ext()) for r in rows if not tax or r["data"].get("taxonomy_id") == tax]
    return page_response(out, total, page, per)


@bp.get("/taxonomy_terms/<rid>")
@api_key_required
def term_one(rid):
    return _one("taxonomy_term", lambda v, r: v.taxonomy_term(r, ext=_ext()))(rid)
