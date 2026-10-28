"""CSV / JSON export. CSV cells are protected against spreadsheet formula injection."""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from . import __version__
from .icp import ICP
from .pipeline import CompanyResult

DISCLAIMER = ("Generated from publicly available pages only. No prospects were contacted. "
              "Facts without a verified evidence quote earn no points. The score supports human review; "
              "it is NOT proof that a company is ready to buy.")

REVIEW_STATUSES = ("Pending review", "Approved", "Rejected", "Needs more research")


def evidence_quality(coverage: float) -> str:
    """Share of the 100 points backed by verified quotes -> High / Medium / Low."""
    return "High" if coverage >= 0.8 else "Medium" if coverage >= 0.5 else "Low"


def _safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def result_row(r: CompanyResult, review: dict[str, str] | None = None) -> dict[str, Any]:
    review = review or {}
    d = r.to_dict()
    crit = {c["name"]: c for c in d["criteria"]}
    pts = lambda n: crit[n]["points"] if n in crit else None  # noqa: E731
    f = r.facts
    evidence = []
    for name, fact in (("industry", f.industry), ("employees", f.employee_count),
                       ("region", f.region), ("business_model", f.business_model)):
        if fact.verified:
            evidence.append(f'{name}={fact.value}: "{fact.evidence}" [{fact.source_url}]')
    for s in f.buying_signals:
        if s.verified:
            evidence.append(f'signal={s.value}: "{s.evidence}" [{s.source_url}]')
    return {
        "Company": r.name, "Website": r.website or "", "Score": d["score"], "Decision": d["decision"],
        "Data Coverage %": round(d["data_coverage"] * 100),
        "Evidence Quality": evidence_quality(d["data_coverage"]),
        "Review Status": review.get("status", REVIEW_STATUSES[0]),
        "Reviewer Notes": review.get("notes", ""),
        "Industry Pts": pts("industry"), "Size Pts": pts("company_size"), "Region Pts": pts("region"),
        "Model Pts": pts("business_model"), "Signals Pts": pts("buying_signals"),
        "Industry": f.industry.value if f.industry.verified else "",
        "Employees": int(f.employee_count.value) if f.employee_count.verified else None,
        "HQ Region": f.region.value if f.region.verified else "",
        "Business Model": f.business_model.value if f.business_model.verified else "",
        "Buying Signals": "; ".join(str(s.value) for s in f.buying_signals if s.verified),
        "Explanation": d["summary"],
        "Flags (missing/unverified)": " | ".join(r.flags),
        "Evidence": " || ".join(evidence),
        "Source URLs": " | ".join(s.url for s in r.sources),
        "Extractor": d["extractor"], "Status": r.status, "Researched At": r.researched_at,
    }


def results_to_dataframe(results: list[CompanyResult], reviews: dict[str, dict[str, str]] | None = None) -> pd.DataFrame:
    reviews = reviews or {}
    return pd.DataFrame([result_row(r, reviews.get(r.name)) for r in results])


def results_to_csv(results: list[CompanyResult], reviews: dict[str, dict[str, str]] | None = None) -> str:
    df = results_to_dataframe(results, reviews)
    df = df.apply(lambda col: col.map(_safe_cell)) if not df.empty else df
    return df.to_csv(index=False)


def results_to_json(results: list[CompanyResult], icp: ICP, reviews: dict[str, dict[str, str]] | None = None) -> str:
    from .models import utc_now
    payload = {"generated_at": utc_now(), "tool_version": __version__, "disclaimer": DISCLAIMER,
               "icp": icp.to_dict(), "results": [{**r.to_dict(), "evidence_quality": evidence_quality(r.score.coverage if r.score else 0.0),
                            "review": (reviews or {}).get(r.name, {"status": REVIEW_STATUSES[0], "notes": ""})}
                           for r in results]}
    return json.dumps(payload, indent=2, ensure_ascii=False)
