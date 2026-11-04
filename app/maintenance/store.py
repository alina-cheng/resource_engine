"""HSDS store contract (read side) -- the surface the worker reads records through.

Only the read operations the detection worker needs are vendored here; the bridge
(`app.services.maintenance_bridge`) implements them over `resource-engine`'s
`HsdsStore` + `app.hsds.nest.Views`, returning fully nested HSDS service records.

Ported from onedegree_resource_engine/contracts/store.py (read surface only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Page:
    """HSDS Page wrapper for list responses."""

    total_items: int
    total_pages: int
    page_number: int
    size: int
    first_page: bool
    last_page: bool
    empty: bool
    contents: list[dict[str, Any]] = field(default_factory=list)  # HSDS service records


@dataclass
class ServiceFilter:
    """Filters for list_services. Supplied filters combine with AND."""

    modified_after: str | None = None
    organization_id: str | None = None
    taxonomy_term_id: str | None = None
    taxonomy_id: str | None = None
    source: str | None = None
    search: str | None = None


@runtime_checkable
class HsdsStore(Protocol):
    """Read operations on the HSDS store. Round-trips to valid nested HSDS."""

    def get_service(self, service_id: str, source: str | None = None) -> dict[str, Any] | None:
        """Return one fully nested HSDS service, or None if not found."""
        ...

    def list_services(self, filt: ServiceFilter, page: int, per_page: int) -> Page:
        """Return a paginated Page of HSDS services matching all supplied filters."""
        ...
