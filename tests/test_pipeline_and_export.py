import csv
import io
import json

import pytest

from leadgen.config import Settings
from leadgen.exporter import results_to_csv, results_to_json
from leadgen.icp import ICP
from leadgen.llm import LLMAuthError, LLMConfigError, LLMRateLimitError
from leadgen.models import CompanyInput, Source
from leadgen.pipeline import run_pipeline
from leadgen.research import ResearchResult

NAMES = ["Lumora Analytics", "Cobalt Secure", "Brightbyte Payments", "Harvest Table Bistro",
         "Titan Steelworks", "Nimbus Freight Software", "Mystery Startup Ltd", "Zephyr Unlisted Corp"]
EXPECTED = {"Lumora Analytics": "Not Qualified", "Cobalt Secure": "Needs Review", "Brightbyte Payments": "Qualified",
            "Harvest Table Bistro": "Not Qualified", "Titan Steelworks": "Qualified",
            "Nimbus Freight Software": "Qualified", "Mystery Startup Ltd": "Insufficient Data",
            "Zephyr Unlisted Corp": "Insufficient Data"}


@pytest.fixture(scope="module")
def demo_results():
    return run_pipeline([CompanyInput(n) for n in NAMES], ICP(), Settings(), mode="demo", extractor="rules")


def test_demo_end_to_end_decisions(demo_results):
    assert {r.name: r.score.decision for r in demo_results} == EXPECTED


def test_prompt_injection_page_does_not_force_100(demo_results):
    cobalt = next(r for r in demo_results if r.name == "Cobalt Secure")
    assert cobalt.score.total == 53.0 and cobalt.score.total < 100  # injected text on its page asked for 100


def test_every_verified_fact_has_a_real_source(demo_results):
    for r in demo_results:
        urls = {s.url for s in r.sources}
        for f in (r.facts.industry, r.facts.employee_count, r.facts.region, r.facts.business_model,
                  *r.facts.buying_signals):
            if f.verified:
                assert f.source_url in urls and f.evidence
        for c in r.score.criteria:
            if c.known and c.evidence:
                assert c.source_url in urls


def test_missing_data_is_flagged(demo_results):
    z = next(r for r in demo_results if r.name == "Zephyr Unlisted Corp")
    assert z.sources == [] and any("missing or unverified" in f for f in z.flags)


def test_progress_callback_and_validation():
    seen = []
    run_pipeline([CompanyInput("Lumora Analytics")], ICP(), Settings(), "demo", "rules",
                 progress=lambda i, n, name: seen.append((i, n, name)))
    assert seen[0][:2] == (0, 1) and seen[-1] == (1, 1, "done")
    with pytest.raises(ValueError):
        run_pipeline([], ICP(), Settings(), "demo", "bogus")
    with pytest.raises(ValueError):
        run_pipeline([], ICP(), Settings(), "nope", "rules")


def test_llm_only_without_key_fails_fast():
    with pytest.raises(LLMConfigError):
        run_pipeline([CompanyInput("Lumora Analytics")], ICP(), Settings(api_key=""), "demo", "llm")


class Boom:
    def research(self, company):
        raise RuntimeError("kaboom")


class OneBad:
    def research(self, company):
        if company.name == "Bad":
            raise RuntimeError("kaboom")
        return ResearchResult(sources=[Source("https://x.test/", "website", "t", "Acme software platform for enterprise teams. We are hiring engineers now.")])


def test_one_failure_does_not_stop_batch():
    res = run_pipeline([CompanyInput("Good"), CompanyInput("Bad"), CompanyInput("Good2")], ICP(), Settings(), "demo", "rules", researcher=OneBad())
    assert [r.status for r in res] == ["ok", "error", "ok"]
    assert "kaboom" in res[1].error and res[1].to_dict()["decision"] == "Error"


class AuthFailLLM:
    calls = 0

    def complete_json(self, *a, **k):
        AuthFailLLM.calls += 1
        raise LLMAuthError("bad key")


class RateLimitedLLM:
    def complete_json(self, *a, **k):
        raise LLMRateLimitError("slow")


def test_llm_auth_error_falls_back_once_and_flags():
    AuthFailLLM.calls = 0
    res = run_pipeline([CompanyInput("Lumora Analytics"), CompanyInput("Cobalt Secure")], ICP(), Settings(api_key="k"),
                       "demo", "llm", llm_client=AuthFailLLM())
    assert AuthFailLLM.calls == 1  # not retried for every company
    assert all(r.status == "ok" and r.facts.extractor == "rules" for r in res)
    assert any("LLM disabled" in f for f in res[0].flags)


def test_llm_rate_limit_falls_back_with_flag():
    res = run_pipeline([CompanyInput("Lumora Analytics")], ICP(), Settings(api_key="k"), "demo", "llm",
                       llm_client=RateLimitedLLM())
    assert res[0].facts.extractor == "rules" and any("LLM extraction failed" in f for f in res[0].flags)


# ---- export
def test_csv_export_shape_and_injection_guard(demo_results):
    rows = list(csv.DictReader(io.StringIO(results_to_csv(demo_results))))
    assert len(rows) == 8 and {"Company", "Score", "Decision", "Evidence", "Source URLs", "Flags (missing/unverified)"} <= set(rows[0])
    assert rows[0]["Source URLs"].startswith("demo://")
    evil = run_pipeline([CompanyInput("=HYPERLINK(1)")], ICP(), Settings(), "demo", "rules")
    assert next(csv.DictReader(io.StringIO(results_to_csv(evil))))["Company"].startswith("'=")


def test_json_export_is_complete(demo_results):
    data = json.loads(results_to_json(demo_results, ICP()))
    assert data["icp"]["name"] and "No prospects were contacted" in data["disclaimer"]
    first = data["results"][0]
    assert first["criteria"] and first["sources"] and "text" not in first["sources"][0]
    assert sum(c["weight"] for c in first["criteria"]) == 100
