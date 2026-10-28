"""Orchestrates: research -> extract -> verify -> score, one company at a time.

A failure on one company never stops the batch; it is recorded on that company's row.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .config import Settings
from .extraction import extract_with_llm, extract_with_rules
from .icp import ICP
from .llm import AnthropicClient, LLMAuthError, LLMConfigError, LLMError
from .models import CompanyInput, ExtractedFacts, Source, utc_now
from .research import DemoResearcher, ResearchResult, WebResearcher
from .scoring import ScoreResult, score_company

log = logging.getLogger(__name__)
MODES = ("live", "demo")
EXTRACTORS = ("auto", "llm", "rules")


class Researcher(Protocol):
    def research(self, company: CompanyInput) -> ResearchResult: ...


@dataclass
class CompanyResult:
    name: str
    website: str | None
    website_origin: str | None
    status: str  # "ok" | "error"
    error: str | None
    facts: ExtractedFacts
    score: ScoreResult | None
    sources: list[Source] = field(default_factory=list)
    research_log: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    researched_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "company": self.name,
            "website": self.website,
            "website_origin": self.website_origin,
            "status": self.status,
            "error": self.error,
            "score": self.score.total if self.score else None,
            "decision": self.score.decision if self.score else "Error",
            "data_coverage": self.score.coverage if self.score else 0.0,
            "summary": self.score.summary if self.score else (self.error or ""),
            "criteria": [vars(c) for c in self.score.criteria] if self.score else [],
            "facts": self.facts.to_dict(),
            "flags": self.flags,
            "sources": [s.public_dict() for s in self.sources],
            "research_log": self.research_log,
            "extractor": self.facts.extractor,
            "researched_at": self.researched_at,
        }


def make_researcher(mode: str, settings: Settings) -> Researcher:
    if mode == "demo":
        return DemoResearcher()
    if mode == "live":
        return WebResearcher(settings)
    raise ValueError(f"Unknown mode {mode!r}; use one of {MODES}")


def run_pipeline(companies: list[CompanyInput], icp: ICP, settings: Settings, mode: str = "demo",
                 extractor: str = "auto", progress: Callable[[int, int, str], None] | None = None,
                 researcher: Researcher | None = None,
                 llm_client: AnthropicClient | None = None) -> list[CompanyResult]:
    if extractor not in EXTRACTORS:
        raise ValueError(f"Unknown extractor {extractor!r}; use one of {EXTRACTORS}")
    icp.validate()
    researcher = researcher or make_researcher(mode, settings)

    use_llm = extractor == "llm" or (extractor == "auto" and settings.has_api_key)
    client = llm_client
    if use_llm and client is None:
        client = AnthropicClient(settings)  # raises LLMConfigError with a clear message
    llm_disabled_reason: str | None = None

    results: list[CompanyResult] = []
    total = len(companies)
    for i, company in enumerate(companies, start=1):
        if progress:
            progress(i - 1, total, company.name)
        extra_flags: list[str] = []
        try:
            research = researcher.research(company)
            facts: ExtractedFacts | None = None
            if use_llm and client is not None and llm_disabled_reason is None and research.sources:
                try:
                    facts = extract_with_llm(company.name, research.sources, icp, client,
                                             model_label=f"llm:{settings.model}")
                except LLMAuthError as exc:
                    llm_disabled_reason = str(exc)
                except LLMError as exc:
                    extra_flags.append(f"LLM extraction failed ({exc}); rules-based extractor used instead.")
            if facts is None:
                if llm_disabled_reason and use_llm:
                    extra_flags.append(f"LLM disabled for this run ({llm_disabled_reason}); rules extractor used.")
                facts = extract_with_rules(research.sources, icp)
            score = score_company(facts, icp)
            results.append(CompanyResult(
                name=company.name, website=research.website, website_origin=research.website_origin,
                status="ok", error=None, facts=facts, score=score, sources=research.sources,
                research_log=research.log,
                flags=_dedupe(research.flags + extra_flags + score.flags)))
        except Exception as exc:  # noqa: BLE001 - isolate per-company failures on purpose
            log.exception("Company %s failed", company.name)
            results.append(CompanyResult(
                name=company.name, website=company.website, website_origin=None, status="error",
                error=f"{type(exc).__name__}: {exc}", facts=ExtractedFacts(), score=None,
                flags=["Processing failed; see error."]))
    if progress:
        progress(total, total, "done")
    return results


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
