"""Ideal Customer Profile (ICP) definition, validation and JSON load/save."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CRITERIA = ("industry", "company_size", "region", "business_model", "buying_signals")

CRITERIA_LABELS = {
    "industry": "Industry fit",
    "company_size": "Company size",
    "region": "Region",
    "business_model": "Business model",
    "buying_signals": "Need for services (tech initiatives / growth signals)",
}

DEFAULT_WEIGHTS = {
    "industry": 25,
    "company_size": 15,
    "region": 15,
    "business_model": 10,
    "buying_signals": 35,
}


class ICPError(ValueError):
    """Raised when an ICP configuration is invalid. Message lists every problem."""


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.splitlines()
    out: list[str] = []
    seen: set[str] = set()
    for item in value or []:
        text = str(item).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text[:80])
    return out[:50]


@dataclass
class ICP:
    name: str = "Cloud / Data / AI consulting ICP"
    target_industries: list[str] = field(default_factory=lambda: [
        "fintech", "banking", "healthcare", "logistics", "manufacturing", "retail", "education"])
    excluded_industries: list[str] = field(default_factory=lambda: [
        "restaurant", "gambling", "data analytics", "artificial intelligence"])
    min_employees: int = 100
    max_employees: int = 5000
    target_regions: list[str] = field(default_factory=lambda: [
        "United States", "Canada", "United Kingdom", "Germany"])
    target_business_model: str = "B2B"
    buying_signal_keywords: list[str] = field(default_factory=lambda: [
        "cloud", "digital transformation", "modernization", "migration", "automation",
        "analytics", "machine learning", "AI", "legacy", "hiring", "expansion"])
    weights: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    qualified_threshold: int = 70
    review_threshold: int = 45
    min_coverage: float = 0.5   # share of the 100 points that must rest on verified data
    unknown_credit: float = 0.0  # fraction of weight given when a criterion is unknown (0 = none)

    # ---- validation -------------------------------------------------------------
    def problems(self) -> list[str]:
        errs: list[str] = []
        if not self.name.strip():
            errs.append("ICP name is required.")
        if not self.target_industries:
            errs.append("Add at least one target industry.")
        if not self.target_regions:
            errs.append("Add at least one target region.")
        if self.min_employees < 0 or self.max_employees < self.min_employees:
            errs.append("Employee range must satisfy 0 <= min <= max.")
        if self.target_business_model not in ("B2B", "B2C"):
            errs.append("Target business model must be B2B or B2C.")
        if set(self.weights) != set(CRITERIA):
            errs.append(f"Weights must define exactly these criteria: {', '.join(CRITERIA)}.")
        else:
            if any((not isinstance(v, int)) or v < 0 for v in self.weights.values()):
                errs.append("Each weight must be a whole number >= 0.")
            elif sum(self.weights.values()) != 100:
                errs.append(f"Weights must add up to 100 (currently {sum(self.weights.values())}).")
        if not (0 <= self.review_threshold <= self.qualified_threshold <= 100):
            errs.append("Thresholds must satisfy 0 <= review <= qualified <= 100.")
        if not (0.0 <= self.min_coverage <= 1.0):
            errs.append("Minimum data coverage must be between 0 and 1.")
        if not (0.0 <= self.unknown_credit <= 0.5):
            errs.append("Unknown-data credit must be between 0 and 0.5.")
        return errs

    def validate(self) -> "ICP":
        errs = self.problems()
        if errs:
            raise ICPError("\n".join(errs))
        return self

    # ---- (de)serialisation ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ICP":
        if not isinstance(data, dict):
            raise ICPError("ICP JSON must be an object.")
        base = cls()
        try:
            icp = cls(
                name=str(data.get("name", base.name)).strip()[:80],
                target_industries=_clean_list(data.get("target_industries", base.target_industries)),
                excluded_industries=_clean_list(data.get("excluded_industries", base.excluded_industries)),
                min_employees=int(data.get("min_employees", base.min_employees)),
                max_employees=int(data.get("max_employees", base.max_employees)),
                target_regions=_clean_list(data.get("target_regions", base.target_regions)),
                target_business_model=str(data.get("target_business_model", base.target_business_model)).upper(),
                buying_signal_keywords=_clean_list(
                    data.get("buying_signal_keywords", base.buying_signal_keywords)),
                weights={k: int(v) for k, v in dict(data.get("weights", base.weights)).items()},
                qualified_threshold=int(data.get("qualified_threshold", base.qualified_threshold)),
                review_threshold=int(data.get("review_threshold", base.review_threshold)),
                min_coverage=float(data.get("min_coverage", base.min_coverage)),
                unknown_credit=float(data.get("unknown_credit", base.unknown_credit)),
            )
        except (TypeError, ValueError) as exc:
            raise ICPError(f"ICP contains a value of the wrong type: {exc}") from exc
        return icp.validate()

    @classmethod
    def load(cls, path: Path | str) -> "ICP":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ICPError(f"Could not read ICP file: {exc}") from exc
        return cls.from_dict(data)

    def save(self, path: Path | str) -> None:
        self.validate()
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
