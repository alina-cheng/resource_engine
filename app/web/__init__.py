from __future__ import annotations
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from app.config import ROOT, Settings
from app.container import Container, build_container
from app.services.chat import ConsentRequired
from app.services.proposals import Stale
from app.services.store import Conflict, ValidationFailed
from app.services.users import AuthError, Principal
from app.jobs.runner import JobError

FRONTEND = ROOT / "frontend"


def err(status: int, message: str, **extra):
    return jsonify({"error": message, **extra}), status


def create_app(settings: Settings | None = None, container: Container | None = None) -> Flask:
    c = container or build_container(settings)
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    app.extensions["c"] = c

    from app.web.routes_app import bp as app_bp
    from app.web.routes_hsds import bp as hsds_bp
    app.register_blueprint(app_bp, url_prefix="/api")
    app.register_blueprint(hsds_bp, url_prefix="/hsds")

    @app.errorhandler(ValidationFailed)
    def _val(e):
        return err(422, "This change would produce invalid HSDS data.", details=e.errors)

    @app.errorhandler(AuthError)
    def _auth(e):
        return err(401, str(e))

    @app.errorhandler(PermissionError)
    def _perm(e):
        return err(403, str(e) or "You do not have access to that.")

    @app.errorhandler(KeyError)
    def _nf(e):
        return err(404, "Not found.")

    @app.errorhandler(Stale)
    def _stale(e):
        return err(409, str(e), stale_fields=e.fields)

    @app.errorhandler(Conflict)
    def _conflict(e):
        return err(409, str(e))

    @app.errorhandler(JobError)
    def _job(e):
        return err(502, str(e))

    @app.errorhandler(ConsentRequired)
    def _consent(e):
        return err(409, "Share your details with providers before sending a request.", code="consent_required")

    @app.errorhandler(413)
    def _big(e):
        return err(413, "That file is larger than 25 MB.")

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/<path:path>")
    def static_files(path):
        if path.startswith(("api/", "hsds/")):
            return err(404, "Not found.")
        f = FRONTEND / path
        if f.is_file():
            return send_from_directory(FRONTEND, path)
        return send_from_directory(FRONTEND, "index.html")

    return app


def container() -> Container:
    from flask import current_app
    return current_app.extensions["c"]


def current_principal() -> Principal | None:
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "):
        return None
    try:
        return container().auth.verify(h[7:])
    except AuthError:
        return None


def auth_required(*roles: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            p = current_principal()
            if not p:
                return err(401, "Log in to continue.")
            if roles and p.role not in roles:
                return err(403, "You do not have access to that.")
            g.principal = p
            return fn(*a, **kw)
        return wrapper
    return deco
