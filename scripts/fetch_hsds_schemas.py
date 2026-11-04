"""Download the official HSDS schema files for a pinned tag (needs network).

    python scripts/fetch_hsds_schemas.py            # v3.2.3 -> schemas/hsds/3.2.3
    python scripts/fetch_hsds_schemas.py v3.2.3

Uses the GitHub API to list /schema at the tag and fetches each *.json file.
After running it, `make test` re-validates the sample ingest against the official schemas.
"""
import json
import sys
import urllib.request
from pathlib import Path

tag = sys.argv[1] if len(sys.argv) > 1 else "v3.2.3"
out = Path(__file__).resolve().parent.parent / "schemas" / "hsds" / tag.lstrip("v")
out.mkdir(parents=True, exist_ok=True)
api = f"https://api.github.com/repos/openreferral/specification/contents/schema?ref={tag}"
with urllib.request.urlopen(api) as r:
    listing = json.load(r)
n = 0
for item in listing:
    if item["name"].endswith(".json") and item.get("download_url"):
        with urllib.request.urlopen(item["download_url"]) as r:
            (out / item["name"]).write_bytes(r.read())
        n += 1
print(f"fetched {n} schema files into {out}")
