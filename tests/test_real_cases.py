"""T18 and T19: real structures, with figures taken from primary sources.

Each example file states its sources. These tests pin the conclusions and
the point each case teaches.
"""

from pathlib import Path

import pytest

from firb_tracer.fgi import determine_fgi
from firb_tracer.model import GovStatus, load_yaml
from firb_tracer.notification import assess

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


# --- T19: COFCO, Mengniu and Bellamy's --------------------------------------


@pytest.fixture
def mengniu():
    return load_yaml(EXAMPLES / "t19_mengniu_bellamys.yaml")


def test_t19_tracing_the_cofco_chain_gives_the_published_deemed_interest(mengniu):
    finding = determine_fgi(mengniu)["HK_Mengniu"]
    assert finding.is_fgi
    # Mengniu AR2025: COFCO deemed interested in 951,110,304 of 3,878,902,513 shares = 24.52%
    assert finding.pct == pytest.approx(24.52, abs=0.01)


def test_t19_bellamys_acquisition_is_notifiable(mengniu):
    decision = assess(mengniu)
    assert decision.notifiable
    assert any("56(1)(a)" in t for t in decision.triggers)


def test_t19_r18_the_largest_direct_holder_alone_gives_the_wrong_answer(mengniu):
    # Enter only COFCO Dairy Investments' own 14.18%, as a reader of one line of
    # the register might, and Mengniu no longer looks like a government investor.
    mengniu.holdings = [h for h in mengniu.holdings
                        if h.held != "HK_Mengniu" or h.holder == "COFCO_DairyInvestments"]
    finding = determine_fgi(mengniu).get("HK_Mengniu")
    assert finding is None or not finding.is_fgi


# --- T18: the Yangtze River Delta guidance fund ------------------------------


@pytest.fixture
def yrd():
    return load_yaml(EXAMPLES / "t18_yrd_guidance_fund.yaml")


def test_t18_the_gp_is_a_government_investor_under_para_d(yrd):
    finding = determine_fgi(yrd)["YRD_GuidanceFund-GP"]
    assert finding.is_fgi and finding.provision == "FATR s 17(1)(d)(i)"
    assert finding.pct == pytest.approx(100.0, abs=0.01)


def test_t18_hypothetical_12_percent_acquisition_is_notifiable(yrd):
    decision = assess(yrd)
    assert decision.notifiable and decision.after.pct == 12


def test_t18_the_result_does_not_depend_on_the_unpublished_split(yrd):
    # Split the 88.21% group row into two state entities: same conclusion (R6).
    from dataclasses import replace

    group = yrd.entities["CN_OtherStateLPs"]
    yrd.entities["CN_OtherStateLPs-B"] = replace(group, id="CN_OtherStateLPs-B", name="Other partners, part B")
    row = next(h for h in yrd.holdings if h.holder == "CN_OtherStateLPs")
    row.distribution_pct = 44.11
    yrd.holdings.append(replace(row, holder="CN_OtherStateLPs-B", distribution_pct=44.10))
    assert determine_fgi(yrd)["YRD_GuidanceFund-GP"].is_fgi


def test_t18_the_three_published_contributions_alone_are_not_enough(yrd):
    # Leave the unpublished partners uncharacterised: the verified 11.79% falls short
    # of 20%, so the conclusion rests on characterising the other partners (R1, R18).
    yrd.entities["CN_OtherStateLPs"].gov_status = GovStatus.UNCERTAIN
    finding = determine_fgi(yrd).get("YRD_GuidanceFund-GP")
    assert finding is None or not finding.is_fgi
