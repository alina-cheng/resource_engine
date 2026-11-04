"""Adapter contract (technical doc 5.4): a source = configuration + one module.

    name            stable source id, used in ids and x_resource_engine.source
    fetch(since)    yields RawBatch objects (the payload exactly as received + its records)
    native_id(rec)  the source's own record id
    map(rec)        one source record -> Mapped (HSDS objects); raise MappingError if impossible
"""
from __future__ import annotations
import glob
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


class MappingError(Exception):
    """A source record cannot be converted to HSDS. The record is quarantined."""


@dataclass
class Resource:
    type: str                       # organization | service | location | service_at_location | taxonomy | taxonomy_term
    id: str
    org_id: str | None
    data: dict


@dataclass
class Mapped:
    native_id: str
    resources: list[Resource]
    warnings: list[str] = field(default_factory=list)


@dataclass
class RawBatch:
    batch_id: str                   # e.g. page number or file name
    raw: bytes                      # exactly as received
    records: list[dict]


@dataclass
class SourceConfig:
    name: str
    adapter: str
    location: str                   # glob of files, or http(s) URL
    enabled: bool = True
    options: dict = field(default_factory=dict)


class SourceAdapter(ABC):
    name: str
    #: JSON key holding the list of records in a page
    @abstractmethod
    def parse_page(self, data: Any) -> list[dict]: ...
    @abstractmethod
    def native_id(self, record: dict) -> str: ...
    @abstractmethod
    def map(self, record: dict) -> Mapped: ...

    def __init__(self, config: SourceConfig, settings):
        self.config, self.settings = config, settings
        self.name = config.name

    # -- fetching: files (demo, tests, partner drops) or HTTP (real APIs) ----
    def fetch(self, since: str | None = None) -> Iterator[RawBatch]:
        loc = self.config.location
        if loc.startswith(("http://", "https://")):
            yield from self.fetch_http(loc, since)
            return
        for path in sorted(glob.glob(loc)):
            raw = Path(path).read_bytes()
            yield RawBatch(Path(path).name, raw, self.parse_page(json.loads(raw)))

    def fetch_http(self, url: str, since: str | None) -> Iterator[RawBatch]:  # pragma: no cover - live
        raise NotImplementedError(f"{type(self).__name__} has no HTTP transport")
