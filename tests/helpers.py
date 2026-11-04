import json
import tempfile
from pathlib import Path

from app.adapters.base import SourceConfig
from app.config import ROOT, load_settings
from app.container import build_container
from app.web import create_app

SAMPLES = ROOT / "data" / "samples"
ODRS = SourceConfig("odrs", "odrs", str(SAMPLES / "BayesExport_20250729.json"))
NDP = SourceConfig("ndp", "ndp", str(SAMPLES / "national-data-platform-sample-*.json"))


def make_container(**overrides):
    d = tempfile.mkdtemp()
    s = load_settings().with_overrides(data_dir=Path(d), database_url=f"sqlite:///{d}/t.db", **overrides)
    return build_container(s)


def generated_container(n_odrs=60, n_ndp=30, seed=3):
    """Container loaded with generated demo data, websites and policy docs."""
    from tools.sample_data_generator.generate import generate
    from tools.sample_data_generator import seed as seed_mod
    d = Path(tempfile.mkdtemp())
    generate(d / "gen", n_odrs, n_ndp, seed)
    seed_mod.GEN = d / "gen"
    c = make_container(website_samples_path=d / "gen" / "websites.json")
    c.settings.sources_path.parent  # noqa: B018
    from dataclasses import replace
    for cfg in (ODRS, NDP):
        pass
    cfgs = [SourceConfig("odrs", "odrs", str(d / "gen" / "odrs" / "*.json")), SourceConfig("ndp", "ndp", str(d / "gen" / "ndp" / "*.json"))]
    for cfg in cfgs:
        c.ingest.run(cfg, "test", "test")
    return c, d / "gen"


def login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.json
    return {"Authorization": f"Bearer {r.json['token']}"}


def app_with_demo():
    """Flask test client with demo users, docs and findings (uses generated data)."""
    c, gen = generated_container()
    from tools.sample_data_generator import seed as seed_mod
    seed_mod.GEN = gen
    c.ingest_all = lambda *a, **k: []          # already imported
    out = seed_mod.seed_demo(c)
    return c, create_app(container=c).test_client(), out, gen
