"""Source registry: sources are configuration (config/sources.json) + an adapter class (R1.2)."""
from __future__ import annotations
import json
import os
from pathlib import Path

from app.adapters.base import SourceAdapter, SourceConfig
from app.adapters.ndp import NdpAdapter
from app.adapters.odrs import OdrsAdapter

ADAPTERS: dict[str, type[SourceAdapter]] = {"odrs": OdrsAdapter, "ndp": NdpAdapter}


def register_adapter(kind: str, cls: type[SourceAdapter]) -> None:
    """Adding a source type = write a SourceAdapter subclass and register it here."""
    ADAPTERS[kind] = cls


def load_source_configs(path: Path) -> list[SourceConfig]:
    if not Path(path).exists():
        return []
    sources = [SourceConfig(**c) for c in json.loads(Path(path).read_text())]
    for source in sources:
        endpoint = os.environ.get(f"{source.name.upper()}_API_URL")
        if endpoint:
            source.location = endpoint
        if source.enabled and os.environ.get("APP_ENV", "local") != "local" and not source.location.startswith("https://"):
            if os.environ.get("ALLOW_SAMPLE_SOURCES", "false").lower() != "true":
                raise ValueError(f"Set {source.name.upper()}_API_URL to the HTTPS data source; sample sources are disabled on AWS.")
    return sources


def build_adapter(cfg: SourceConfig, settings) -> SourceAdapter:
    if cfg.adapter not in ADAPTERS:
        raise KeyError(f"no adapter registered for '{cfg.adapter}'")
    return ADAPTERS[cfg.adapter](cfg, settings)
