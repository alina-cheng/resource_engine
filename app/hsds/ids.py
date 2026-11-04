"""Deterministic HSDS identifiers (UUIDv5) so re-ingest updates instead of duplicating (R1.6)."""
import uuid

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://resource-engine.1degree.org/hsds")


def make_id(source: str, kind: str, *parts: object) -> str:
    key = "|".join([source, kind, *[str(p) for p in parts]])
    return str(uuid.uuid5(NAMESPACE, key))
