"""Source registry: sources are configuration (config/sources.json) + an adapter class (R1.2)."""
from __future__ import annotations
import json
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
    return [SourceConfig(**c) for c in json.loads(Path(path).read_text())]


def build_adapter(cfg: SourceConfig, settings) -> SourceAdapter:
    if cfg.adapter not in ADAPTERS:
        raise KeyError(f"no adapter registered for '{cfg.adapter}'")
    return ADAPTERS[cfg.adapter](cfg, settings)
