"""Deterministic HSDS identifiers (UUIDv5) so re-ingest updates instead of duplicating (R1.6)."""
import uuid

NAMESPACE = uuid.UUID("6f1c2a52-6b0e-4a5e-9d3a-2f3b7d0c9e41")


def make_id(source: str, kind: str, *parts: object) -> str:
    key = ":".join([source, kind, *[str(p) for p in parts]])
    return str(uuid.uuid5(NAMESPACE, key))
