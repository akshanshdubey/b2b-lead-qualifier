"""Transparent, deterministic scoring (no LLM involved, so it is fully testable).

Total = sum of five criteria whose weights come from the ICP and add up to 100.
Rules:
  * Only VERIFIED facts (quote confirmed in a retrieved page) earn points.
  * Unknown / unverified criteria earn `icp.unknown_credit` of their weight (default 0).
  * `coverage` = share of the 100 points that rest on verified data.
  * Verified excluded industry => disqualified, whatever the score.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .icp import CRITERIA_LABELS, ICP
from .models import ExtractedFacts, Fact
from .regions import region_matches

QUALIFIED = "Qualified"
REVIEW = "Needs Review"
NOT_QUALIFIED = "Not Qualified"
INSUFFICIENT = "Insufficient Data"
DECISIONS = (QUALIFIED, REVIEW, NOT_QUALIFIED, INSUFFICIENT)

SIGNAL_CREDIT = {0: 0.0, 1: 0.5, 2: 0.8}  # 3+ signals = 100%


@dataclass
class CriterionScore:
    name: str
    label: str
    weight: int
    points: float
    status: str  # match | partial | mismatch | excluded | none_found | unknown
    explanation: str
    known: bool
    evidence: str | None = None
    source_url: str | None = None


@dataclass
class ScoreResult:
    total: float
    decision: str
    coverage: float
    criteria: list[CriterionScore]
    summary: str
    flags: list[str] = field(default_factory=list)
    disqualified_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _matches_any(value: str, options: list[str]) -> str | None:
    v = value.lower().strip()
    for opt in options:
        o = opt.lower().strip()
        if o and (o in v or v in o):
            return opt
    return None


def _build(name: str, icp: ICP, fraction: float, status: str, text: str,
           fact: Fact | None, known: bool = True) -> CriterionScore:
    weight = icp.weights[name]
    pts = round(weight * fraction, 1)
    text = f"{text} ({pts:g}/{weight} pts)"
    return CriterionScore(name=name, label=CRITERIA_LABELS[name], weight=weight, points=pts,
                          status=status, explanation=text, known=known,
                          evidence=fact.evidence if fact and known else None,
                          source_url=fact.source_url if fact and known else None)


def _unknown(name: str, icp: ICP, fact: Fact | None, what: str, flags: list[str]) -> CriterionScore:
    label = CRITERIA_LABELS[name]
    if fact is not None and fact.value is not None and not fact.verified:
        why = f"reported value {fact.value!r} was rejected: {fact.issue or 'could not be verified'}"
    else:
        why = (fact.issue if fact and fact.issue else "not found in the retrieved pages")
    flags.append(f"{label}: missing or unverified - {why}")
    credit = icp.unknown_credit
    note = "no points awarded" if credit == 0 else f"{credit:.0%} benefit-of-doubt credit"
    return _build(name, icp, credit, "unknown", f"{what} unknown ({why}); {note}", fact, known=False)


def _ok(f: Fact | None) -> bool:
    return bool(f and f.verified and f.value is not None)


def score_company(facts: ExtractedFacts, icp: ICP) -> ScoreResult:
    icp.validate()
    flags: list[str] = []
    crits: list[CriterionScore] = []
    disq: str | None = None

    # 1. industry
    f = facts.industry
    if not _ok(f):
        crits.append(_unknown("industry", icp, f, "Industry", flags))
    else:
        v = str(f.value)
        if (bad := _matches_any(v, icp.excluded_industries)):
            disq = f"Industry '{v}' is on the ICP exclusion list ('{bad}')."
            crits.append(_build("industry", icp, 0, "excluded", f"Industry '{v}' is excluded by the ICP", f))
        elif (good := _matches_any(v, icp.target_industries)):
            crits.append(_build("industry", icp, 1, "match", f"Industry '{v}' matches target '{good}'", f))
        else:
            crits.append(_build("industry", icp, 0, "mismatch", f"Industry '{v}' is not a target industry", f))

    # 2. company size
    f = facts.employee_count
    if not _ok(f):
        crits.append(_unknown("company_size", icp, f, "Employee count", flags))
    else:
        n, lo, hi = int(f.value), icp.min_employees, icp.max_employees
        if lo <= n <= hi:
            crits.append(_build("company_size", icp, 1, "match", f"{n:,} employees is within {lo:,}-{hi:,}", f))
        elif lo * 0.5 <= n < lo or hi < n <= hi * 2:
            crits.append(_build("company_size", icp, 0.5, "partial",
                                f"{n:,} employees is close to the {lo:,}-{hi:,} range (within 50%/2x)", f))
        else:
            crits.append(_build("company_size", icp, 0, "mismatch", f"{n:,} employees is outside {lo:,}-{hi:,}", f))

    # 3. region
    f = facts.region
    if not _ok(f):
        crits.append(_unknown("region", icp, f, "Headquarters region", flags))
    else:
        matched, target = region_matches(str(f.value), icp.target_regions)
        if matched:
            crits.append(_build("region", icp, 1, "match", f"Region '{f.value}' matches target '{target}'", f))
        else:
            crits.append(_build("region", icp, 0, "mismatch", f"Region '{f.value}' is not in the target regions", f))

    # 4. business model
    f = facts.business_model
    if not _ok(f):
        crits.append(_unknown("business_model", icp, f, "Business model", flags))
    else:
        model, target = str(f.value).upper(), icp.target_business_model
        if model == target:
            crits.append(_build("business_model", icp, 1, "match", f"Business model {model} matches target {target}", f))
        elif model == "BOTH":
            crits.append(_build("business_model", icp, 0.7, "partial", f"Serves both B2B and B2C (target {target})", f))
        else:
            crits.append(_build("business_model", icp, 0, "mismatch", f"Business model {model} differs from target {target}", f))

    # 5. buying signals
    good_signals = [s for s in facts.buying_signals if s.verified]
    rejected = [s for s in facts.buying_signals if not s.verified]
    for s in rejected:
        flags.append(f"Buying signal '{s.value}' rejected: {s.issue}")
    if not facts.pages_available:
        crits.append(_unknown("buying_signals", icp, None, "Buying signals", flags))
    elif not good_signals:
        crits.append(_build("buying_signals", icp, 0, "none_found",
                            "No verified buying signals found in the retrieved pages", None))
    else:
        n = len(good_signals)
        names = ", ".join(sorted({str(s.value) for s in good_signals}))
        c = SIGNAL_CREDIT.get(n, 1.0)
        first = good_signals[0]
        cs = _build("buying_signals", icp, c, "match" if c == 1 else "partial",
                    f"{n} verified signal(s): {names}", first)
        crits.append(cs)

    total = round(max(0.0, min(100.0, sum(c.points for c in crits))), 1)
    coverage = round(sum(c.weight for c in crits if c.known) / 100, 2)
    decision = _decide(total, coverage, disq, icp)
    summary = _summary(decision, total, coverage, crits, disq)
    return ScoreResult(total=total, decision=decision, coverage=coverage, criteria=crits,
                       summary=summary, flags=flags, disqualified_reason=disq)


def _decide(total: float, coverage: float, disq: str | None, icp: ICP) -> str:
    if disq:
        return NOT_QUALIFIED
    if total >= icp.qualified_threshold:
        return QUALIFIED if coverage >= icp.min_coverage else REVIEW
    if coverage < icp.min_coverage and total < icp.review_threshold:
        return INSUFFICIENT
    if total >= icp.review_threshold:
        return REVIEW
    return NOT_QUALIFIED


def _summary(decision: str, total: float, coverage: float, crits: list[CriterionScore],
             disq: str | None) -> str:
    head = f"{decision}: {total:g}/100 with {coverage:.0%} of the score backed by verified evidence."
    if disq:
        return f"{head} Disqualified: {disq}"
    best = [c.label for c in crits if c.status == "match"]
    gaps = [c.label for c in crits if c.status in ("mismatch", "none_found")]
    unk = [c.label for c in crits if c.status == "unknown"]
    parts = [head]
    if best:
        parts.append("Strong fit: " + ", ".join(best) + ".")
    if gaps:
        parts.append("Weak fit: " + ", ".join(gaps) + ".")
    if unk:
        parts.append("Could not verify: " + ", ".join(unk) + ".")
    return " ".join(parts)
