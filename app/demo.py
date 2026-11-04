"""One command demo: generate sample data (if missing), load it, seed demo users/documents, then serve.

    python -m app.demo            # http://127.0.0.1:8000
    python -m app.demo --reset    # wipe the local database first
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
from pathlib import Path

from app.config import ROOT, load_settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-serve", action="store_true")
    a = ap.parse_args()
    # The demo runs on generated data in its own folder, so --reset cannot wipe a real import.
    os.environ.setdefault("SOURCES_CONFIG", str(ROOT / "config" / "sources.demo.json"))
    os.environ.setdefault("DATA_DIR", str(ROOT / "var" / "demo"))
    s = load_settings()
    if a.reset and s.data_dir.exists():
        shutil.rmtree(s.data_dir)
    gen = ROOT / "data" / "generated"
    if not (gen / "websites.json").exists():
        from tools.sample_data_generator.generate import generate
        print("Generating sample data:", json.dumps(generate(gen)))
    from app.main import _container, app
    from tools.sample_data_generator.seed import seed_demo
    out = seed_demo(_container) if _container.store.counts().get("service", 0) == 0 or not _container.users.by_email("admin@demo.org") else {"note": "already seeded"}
    print(json.dumps({k: v for k, v in out.items() if k in ("credentials", "api_keys", "maintenance", "note")}, indent=2))
    if not a.no_serve:
        print("\nOpen http://127.0.0.1:8000\n")
        app.run(host="127.0.0.1", port=8000, threaded=True)


if __name__ == "__main__":
    main()
