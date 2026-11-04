"""Website source contract -- the replaceable interface for fetching site content.

The bridge (`app.services.maintenance_bridge`) implements this over
`resource-engine`'s existing `app.services.website` sources, so nothing in the
engine knows whether pages come from sample content or the live web.

Ported verbatim from onedegree_resource_engine/contracts/website_source.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class WebsiteResult:
    """The result of fetching a URL.

    A non-None ``error`` (or an unreachable/expired-cert status) drives the
    ``actively_bad`` / ``check_failed`` categories -- never a silent skip.
    """

    content: str | None  # page text, or None on failure
    status: int | None  # HTTP status, or None if the request never completed
    error: str | None  # non-None on failure (timeout, DNS, TLS, etc.)


@runtime_checkable
class WebsiteSource(Protocol):
    """Given a URL, return its content, HTTP status, and any error."""

    def get(self, url: str) -> WebsiteResult: ...
