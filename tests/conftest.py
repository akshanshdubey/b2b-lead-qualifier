import pytest

from leadgen.config import Settings
from leadgen.icp import ICP as _ICP
from leadgen.models import ExtractedFacts, Fact


LEGACY = dict(
    target_industries=["software", "saas", "cybersecurity", "fintech", "data analytics", "artificial intelligence"],
    excluded_industries=["restaurant", "retail", "gambling"], min_employees=50, max_employees=1000,
    buying_signal_keywords=["hiring", "funding", "series", "expansion", "partnership", "integration", "launch", "AI"],
    weights={"industry": 25, "company_size": 20, "region": 15, "business_model": 15, "buying_signals": 25})


def ICP(**kw):  # noqa: N802 - scoring tests use a fixed, generic profile so their arithmetic stays stable
    return _ICP(**{**LEGACY, **kw})


@pytest.fixture
def icp():
    return ICP()


@pytest.fixture
def settings():
    return Settings(api_key="test-key-123", crawl_delay_seconds=0)


def vf(value, quote="This sentence is the evidence quote.", url="https://x.test/"):
    return Fact(value=value, evidence=quote, source_url=url, verified=True)


@pytest.fixture
def perfect_facts():
    return ExtractedFacts(
        industry=vf("software"), employee_count=vf(300), region=vf("Austin, Texas, United States"),
        business_model=vf("B2B"),
        buying_signals=[vf("hiring"), vf("funding"), vf("launch")],
        extractor="test", pages_available=True)
