"""Plain data containers shared across the pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CompanyInput:
    name: str
    website: str | None = None  # normalized origin such as https://example.com


@dataclass
class Source:
    """A public page that was actually retrieved (or a bundled demo fixture)."""

    url: str
    kind: str  # "website" | "wikipedia" | "demo"
    title: str
    text: str
    fetched_at: str = field(default_factory=utc_now)

    def public_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "kind": self.kind,
            "title": self.title,
            "fetched_at": self.fetched_at,
            "text_chars": len(self.text),
        }


@dataclass
class Fact:
    """One extracted data point. Only `verified` facts earn score points."""

    value: Any = None
    evidence: str | None = None  # verbatim quote from a fetched page
    source_url: str | None = None
    verified: bool = False
    issue: str | None = None  # why it is missing or unverified

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedFacts:
    industry: Fact = field(default_factory=Fact)
    employee_count: Fact = field(default_factory=Fact)
    region: Fact = field(default_factory=Fact)
    business_model: Fact = field(default_factory=Fact)
    buying_signals: list[Fact] = field(default_factory=list)
    extractor: str = "none"
    pages_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
