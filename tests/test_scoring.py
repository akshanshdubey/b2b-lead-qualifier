import pytest

from leadgen.icp import ICP as RealICP, ICPError
from leadgen.models import ExtractedFacts, Fact
from leadgen.scoring import INSUFFICIENT, NOT_QUALIFIED, QUALIFIED, REVIEW, score_company
from conftest import ICP, vf


def test_perfect_match_scores_100(perfect_facts, icp):
    r = score_company(perfect_facts, icp)
    assert r.total == 100.0 and r.decision == QUALIFIED and r.coverage == 1.0
    assert not r.flags


def test_total_equals_sum_of_criteria(perfect_facts, icp):
    r = score_company(perfect_facts, icp)
    assert r.total == pytest.approx(sum(c.points for c in r.criteria))
    assert sum(c.weight for c in r.criteria) == 100


def test_unverified_fact_earns_nothing_and_is_flagged(perfect_facts, icp):
    perfect_facts.industry = Fact(value="software", evidence="made up", verified=False,
                                  issue="Quote not found in any retrieved page (possible hallucination).")
    r = score_company(perfect_facts, icp)
    ind = next(c for c in r.criteria if c.name == "industry")
    assert ind.points == 0 and ind.status == "unknown" and not ind.known
    assert any("rejected" in f and "Industry" in f for f in r.flags)
    assert r.coverage == 0.75


def test_unknown_everything_is_insufficient(icp):
    r = score_company(ExtractedFacts(pages_available=False), icp)
    assert r.total == 0 and r.decision == INSUFFICIENT and r.coverage == 0.0
    assert len(r.flags) == 5


def test_excluded_industry_is_disqualified_even_with_high_other_scores(perfect_facts, icp):
    perfect_facts.industry = vf("restaurant")
    r = score_company(perfect_facts, icp)
    assert r.total == 75.0  # everything except industry
    assert r.decision == NOT_QUALIFIED and r.disqualified_reason


@pytest.mark.parametrize("n,expected", [(50, 20), (1000, 20), (49, 20), (25, 10), (24, 0),
                                        (1001, 10), (2000, 10), (2001, 0)])
def test_company_size_boundaries(perfect_facts, icp, n, expected):
    # 49 employees is within 50% below the minimum (>=25) so it is partial credit (10)
    if n == 49:
        expected = 10
    perfect_facts.employee_count = vf(n)
    pts = next(c.points for c in score_company(perfect_facts, icp).criteria if c.name == "company_size")
    assert pts == expected


@pytest.mark.parametrize("region,pts", [("Toronto, Ontario, Canada", 15), ("Berlin, Germany", 15),
                                        ("Sydney, Australia", 0), ("Boston, MA", 15), ("Lahore, Pakistan", 0)])
def test_region_matching(perfect_facts, icp, region, pts):
    perfect_facts.region = vf(region)
    got = next(c.points for c in score_company(perfect_facts, icp).criteria if c.name == "region")
    assert got == pts


def test_region_group_matches_europe():
    icp = ICP(target_regions=["Europe"])
    facts = ExtractedFacts(region=vf("Rotterdam, Netherlands"), pages_available=True)
    assert next(c for c in score_company(facts, icp).criteria if c.name == "region").points == 15


@pytest.mark.parametrize("model,pts", [("B2B", 15), ("BOTH", 10.5), ("B2C", 0)])
def test_business_model(perfect_facts, icp, model, pts):
    perfect_facts.business_model = vf(model)
    assert next(c.points for c in score_company(perfect_facts, icp).criteria if c.name == "business_model") == pts


@pytest.mark.parametrize("n,pts", [(0, 0), (1, 12.5), (2, 20), (3, 25), (6, 25)])
def test_signal_credit(perfect_facts, icp, n, pts):
    perfect_facts.buying_signals = [vf(f"s{i}") for i in range(n)]
    assert next(c.points for c in score_company(perfect_facts, icp).criteria if c.name == "buying_signals") == pts


def test_unverified_signals_do_not_count(perfect_facts, icp):
    perfect_facts.buying_signals = [Fact(value="hiring", evidence="fake", verified=False, issue="not found")]
    r = score_company(perfect_facts, icp)
    assert next(c.points for c in r.criteria if c.name == "buying_signals") == 0
    assert any("rejected" in f for f in r.flags)


def test_thresholds_and_review_band(perfect_facts):
    icp = ICP()
    perfect_facts.region = vf("Sydney, Australia")      # -15
    perfect_facts.employee_count = vf(30)                # -> partial: 10 of 20
    perfect_facts.buying_signals = [vf("hiring")]        # 12.5 of 25
    r = score_company(perfect_facts, icp)                # 25+10+0+15+12.5 = 62.5
    assert r.total == 62.5 and r.decision == REVIEW


def test_low_coverage_blocks_qualified():
    icp = ICP(unknown_credit=0.5, min_coverage=0.5)
    facts = ExtractedFacts(industry=vf("software"), pages_available=False)
    r = score_company(facts, icp)
    assert r.coverage == 0.25 and r.total > 0 and r.coverage < 0.5 and r.decision != QUALIFIED


def test_custom_weights_change_score(perfect_facts):
    icp = ICP(weights={"industry": 50, "company_size": 10, "region": 10, "business_model": 10, "buying_signals": 20})
    assert score_company(perfect_facts, icp).total == 100.0
    perfect_facts.industry = vf("manufacturing")
    assert score_company(perfect_facts, icp).total == 50.0


def test_scoring_is_deterministic(perfect_facts, icp):
    assert score_company(perfect_facts, icp).to_dict() == score_company(perfect_facts, icp).to_dict()


# ---- ICP validation
def test_icp_weights_must_sum_to_100():
    with pytest.raises(ICPError, match="add up to 100"):
        ICP(weights={"industry": 50, "company_size": 20, "region": 15, "business_model": 15, "buying_signals": 25}).validate()


@pytest.mark.parametrize("bad", [{"min_employees": 500, "max_employees": 10},
                                 {"qualified_threshold": 30, "review_threshold": 60},
                                 {"target_business_model": "B2X"}, {"target_industries": []}])
def test_icp_rejects_bad_values(bad):
    with pytest.raises(ICPError):
        RealICP.from_dict(bad)


def test_icp_roundtrip(tmp_path, icp):
    p = tmp_path / "icp.json"
    icp.save(p)
    assert RealICP.load(p) == icp


def test_icp_load_missing_file():
    with pytest.raises(ICPError):
        RealICP.load("does-not-exist.json")
