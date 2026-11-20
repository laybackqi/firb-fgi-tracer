"""Tests for steps 3 and 4: associates and foreign government investor status.

Case numbers refer to the test list in the rules document.
"""

from firb_tracer.fgi import determine_fgi
from firb_tracer.model import from_dict


def gov(id_, country, status="FG"):
    return {"id": id_, "name": id_, "kind": "government", "country": country,
            "gov_status": status, "gov_reason": "test"}


def sge(id_, country):
    return {"id": id_, "name": id_, "kind": "corporation", "country": country,
            "gov_status": "SGE", "gov_reason": "test"}


def corp(id_, **extra):
    return {"id": id_, "name": id_, "kind": "corporation", **extra}


def hold(holder, held, pct=0, **extra):
    return {"holder": holder, "held": held, "shares_pct": pct, "source": "test", **extra}


def run(entities, holdings):
    return determine_fgi(from_dict({"entities": entities, "holdings": holdings}))


# --- (a) and (b)(i): one government -------------------------------------------


def test_governments_are_investors_under_para_a():
    f = run([gov("sz", "CN"), sge("metro", "CN")], [])
    assert f["sz"].provision == "FATR s 17(1)(a)"
    assert f["metro"].provision == "FATR s 17(1)(a)"


def test_t01_exactly_20_percent():
    f = run([gov("sz", "CN"), corp("a")], [hold("sz", "a", 20)])
    assert f["a"].provision == "FATR s 17(1)(b)(i)"


def test_19_9_percent_alone_is_not_enough():
    f = run([gov("sz", "CN"), corp("a")], [hold("sz", "a", 19.9)])
    assert "a" not in f


# --- s 6(1)(l): same-country aggregation -------------------------------------


def test_t04_two_municipal_sasacs_are_associates():
    f = run([gov("sz", "CN"), gov("gz", "CN"), corp("d")], [hold("sz", "d", 12), hold("gz", "d", 10)])
    d = f["d"]
    assert d.provision == "FATR s 17(1)(b)(i)"
    assert d.pct == 22
    assert "s 6(1)(l)(i)" in d.members["gz"] or "s 6(1)(l)(i)" in d.members.get("sz", "")


def test_t06_three_tiers_of_chinese_state_aggregate():
    f = run(
        [gov("sz", "CN"), sge("central_soe", "CN"), sge("county_lgfv", "CN"), corp("h")],
        [hold("sz", "h", 8), hold("central_soe", "h", 7), hold("county_lgfv", "h", 6)],
    )
    assert f["h"].pct == 21
    assert f["h"].provision == "FATR s 17(1)(b)(i)"


def test_t10_19_percent_plus_a_2_percent_soe():
    f = run(
        [gov("sz", "CN"), sge("central_soe", "CN"), corp("holdco")],
        [hold("sz", "holdco", 19), hold("central_soe", "holdco", 2)],
    )
    assert f["holdco"].pct == 21


def test_t08_different_countries_are_not_associates():
    f = run(
        [sge("sg", "SG"), gov("sz", "CN"), sge("no", "NO"), corp("k")],
        [hold("sg", "k", 15), hold("sz", "k", 10), hold("no", "k", 10)],
    )
    assert "k" not in f  # 15% is the largest single group; 35% < 40%


def test_t08_variant_concert_party_across_countries():
    f = run(
        [sge("sg", "SG"), gov("sz", "CN"), sge("no", "NO"), corp("k")],
        [hold("sg", "k", 15, concert_with=["sz"]), hold("sz", "k", 10), hold("no", "k", 10)],
    )
    assert f["k"].provision == "FATR s 17(1)(b)(i)"
    assert f["k"].pct == 25
    assert any("s 6(1)(b)" in why for why in f["k"].members.values())


# --- s 6(1)(f): non-equity control -------------------------------------------


def test_t07_entity_acting_on_sasac_wishes_is_an_associate():
    f = run(
        [gov("sz", "CN"), corp("x", acts_on_wishes_of=["sz"]), corp("j")],
        [hold("sz", "x", 15), hold("x", "j", 15), hold("sz", "j", 6)],
    )
    assert "x" not in f  # 15% alone does not make X an investor
    assert f["j"].provision == "FATR s 17(1)(b)(i)"
    assert f["j"].pct == 21
    assert f["j"].via == "sz"  # the government is the holder (R10)


# --- (e): the status passes down the chain -----------------------------------


def test_t05_status_passes_down_without_multiplying():
    f = run(
        [sge("metro", "CN"), corp("e"), corp("f"), corp("g")],
        [hold("metro", "e", 30), hold("e", "f", 25), hold("f", "g", 20)],
    )
    assert f["e"].provision == "FATR s 17(1)(b)(i)"
    assert f["f"].provision == "FATR s 17(1)(e)(i), read with (b)(i)"
    assert f["g"].provision == "FATR s 17(1)(e)(ii), read with (b)(i)"
    assert [f[x].round for x in "efg"] == [1, 2, 3]
    # The government's economic share in G is only 1.5%, yet G is an investor.


def test_an_investor_found_later_joins_the_same_country_group():
    # E becomes an investor in round 1; in round 2 it is an associate of the
    # Ganzhou SASAC under s 6(1)(l)(iii), and their holdings in T combine.
    f = run(
        [gov("sz", "CN"), gov("gz", "CN"), corp("e"), corp("t")],
        [hold("sz", "e", 30), hold("e", "t", 12), hold("gz", "t", 9)],
    )
    assert f["t"].pct == 21
    assert f["t"].round == 2


# --- veto (s 22(4)) ----------------------------------------------------------


def test_t12_guidance_fund_with_5_percent_and_a_veto():
    f = run([sge("fund", "CN"), corp("jv")], [hold("fund", "jv", 5, veto=True)])
    assert f["jv"].provision == "FATR s 17(1)(b)(i)"
    assert f["jv"].pct == 20


# --- trusts and partnerships -------------------------------------------------


def test_t13_guidance_fund_lp_makes_the_gp_an_investor():
    gp = {"id": "gp", "name": "GP of Fund", "kind": "general_partner", "capacity_of": "Fund LP"}
    f = run([sge("guidance", "CN"), gp], [hold("guidance", "gp", 0, distribution_pct=25)])
    assert f["gp"].provision == "FATR s 17(1)(d)(i)"


def test_t16_discretionary_trust_counts_the_maximum():
    tr = {"id": "tr", "name": "Trustee of Trust A", "kind": "trustee", "capacity_of": "Trust A"}
    f = run([sge("soe", "CN"), tr], [hold("soe", "tr", 0, distribution_pct=5, max_distribution_pct=100)])
    assert f["tr"].provision == "FATR s 17(1)(c)(i)"


# --- (ii) and the s 17(2) exception ------------------------------------------


def test_t03_three_countries_reach_40_percent():
    f = run(
        [sge("sg", "SG"), sge("me", "AE"), gov("sz", "CN"), corp("c")],
        [hold("sg", "c", 18), hold("me", "c", 15), hold("sz", "c", 10)],
    )
    c = f["c"]
    assert c.provision == "FATR s 17(1)(b)(ii)"
    assert c.only_aggregate and c.is_fgi
    assert c.exemption.startswith("possible")


def test_t20_single_government_at_20_percent_rules_out_the_exception():
    f = run(
        [gov("cn", "CN"), sge("sg", "SG"), corp("fund", fund_exemption_claimed=True)],
        [hold("cn", "fund", 25), hold("sg", "fund", 20)],
    )
    assert f["fund"].provision == "FATR s 17(1)(b)(i)"
    assert f["fund"].is_fgi
    assert not f["fund"].only_aggregate


def test_t22_single_government_at_60_percent_however_passive():
    f = run([gov("cn", "CN"), corp("fund", fund_exemption_claimed=True)], [hold("cn", "fund", 60)])
    assert f["fund"].provision == "FATR s 17(1)(b)(i)"


def test_t23_only_the_40_percent_test_and_exception_confirmed():
    f = run(
        [gov("cn", "CN"), sge("sg", "SG"), sge("no", "NO"), corp("fund", fund_exemption_claimed=True)],
        [hold("cn", "fund", 15), hold("sg", "fund", 15), hold("no", "fund", 12)],
    )
    assert not f["fund"].is_fgi
    assert f["fund"].exemption.startswith("applied")


def test_t24_a_veto_brings_the_fund_within_i_so_no_exception():
    f = run(
        [gov("cn", "CN"), sge("sg", "SG"), sge("no", "NO"), corp("fund", fund_exemption_claimed=True)],
        [hold("cn", "fund", 15, veto=True), hold("sg", "fund", 15), hold("no", "fund", 12)],
    )
    assert f["fund"].is_fgi
    assert f["fund"].provision == "FATR s 17(1)(b)(i)"


def test_t25_two_countries_below_20_cannot_reach_40():
    f = run(
        [gov("cn", "CN"), sge("sg", "SG"), corp("fund")],
        [hold("cn", "fund", 19.9), hold("sg", "fund", 19.9)],
    )
    assert "fund" not in f


def test_s45_5_an_aggregate_only_investor_has_no_same_country_associates():
    # C is an investor only under (ii). C and the Ganzhou SASAC each hold 12%
    # of T: no s 6(1)(l) association, so neither reaches 20%.
    f = run(
        [sge("sg", "SG"), sge("me", "AE"), gov("sz", "CN"), gov("gz", "CN"), corp("c"), corp("t")],
        [hold("sg", "c", 18), hold("me", "c", 15), hold("sz", "c", 10),
         hold("c", "t", 12), hold("gz", "t", 12)],
    )
    assert f["c"].only_aggregate
    assert "t" not in f
