"""One HSDS rulebook for the whole system: the ingest transform's validate().

It checks the pinned v3.2.3 schemas in contracts/hsds/schema, the tabular required fields, and the
Resource Engine quality rules, so a record is judged the same at ingest and on every later edit.
"""

from __future__ import annotations

from pathlib import Path
from app.adapters.transform.hsds import HSDS_VERSION, SCHEMA_DIR, validate


class HsdsValidator:
    def __init__(self, schema_dir=None, version="3.2.3") -> None:
        if version != HSDS_VERSION:
            raise ValueError(f"This transform requires HSDS {HSDS_VERSION}")
        if schema_dir is not None and Path(schema_dir).resolve() != SCHEMA_DIR.resolve():
            raise ValueError("Set HSDS_SCHEMA_DIR before starting the process so ingest and API share one schema registry")
        self.version = HSDS_VERSION

    def errors(self, kind: str, data: dict) -> list[str]:
        return validate(kind, data)

    def engine(self) -> str:
        return f"jsonschema, official HSDS v{self.version}"

    def is_valid(self, kind: str, data: dict) -> bool:
        return not self.errors(kind, data)
