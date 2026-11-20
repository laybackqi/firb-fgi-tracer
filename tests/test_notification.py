"""Tests for step 6: direct interest and notification under FATR s 16 and s 56.

Case numbers refer to the test list in the rules document.
"""

from firb_tracer.model import from_dict
from firb_tracer.notification import assess

from test_fgi import corp, gov, hold, sge


def decide(entities, holdings, buyer, target=None, **tx):
    return assess(from_dict({
        "entities": entities, "holdings": holdings,
        "buyer": buyer, "target": target, "transaction": tx or None,
    }))


def test_offshore_purchase_of_a_holdco_is_notifiable():
    # The opening example: a Shenzhen SOE buys 25% of a Hong Kong holdco that
    # holds 12% of an Australian miner. No Australian shares change hands.
    d = decide(
        [sge("sz_soe", "CN"), corp("hk_holdco"), corp("au_miner")],
        [hold("sz_soe", "hk_holdco", 25, proposed=True), hold("hk_holdco", "au_miner", 12)],
        "sz_soe", "au_miner", target_is_mining_entity=True,
    )
    assert d.notifiable
    assert (d.before.pct, d.after.pct) == (0, 12)
    assert d.direct_interest.startswith("FATR s 16(a)")
    assert any("56(1)(a)" in t for t in d.triggers)
    assert any("56(1)(c)(ii)" in t for t in d.triggers)


def test_the_same_deal_at_19_percent_traces_nothing():
    d = decide(
        [sge("sz_soe", "CN"), corp("hk_holdco"), corp("au_miner")],
        [hold("sz_soe", "hk_holdco", 19, proposed=True), hold("hk_holdco", "au_miner", 12)],
        "sz_soe", "au_miner",
    )
    assert not d.notifiable
    assert d.after.pct == 0


def test_exactly_10_percent_is_a_direct_interest():
    d = decide([sge("soe", "CN"), corp("au")], [hold("soe", "au", 10, proposed=True)], "soe", "au")
    assert d.notifiable


def test_t14_fund_gp_takes_8_percent_and_a_board_seat():
    gp = {"id": "gp", "name": "GP of Fund", "kind": "general_partner", "capacity_of": "Fund LP"}
    d = decide(
        [sge("guidance", "CN"), gp, corp("au_tech")],
        [hold("guidance", "gp", 0, distribution_pct=25),
         hold("gp", "au_tech", 8, board_seats="1/7", proposed=True)],
        "gp", "au_tech",
    )
    assert d.buyer_is_fgi
    assert d.direct_interest.startswith("FATR s 16(c)")
    assert d.notifiable


def test_t15_same_fund_8_percent_without_a_seat_is_not_notifiable_but_flagged():
    gp = {"id": "gp", "name": "GP of Fund", "kind": "general_partner", "capacity_of": "Fund LP"}
    d = decide(
        [sge("guidance", "CN"), gp, corp("au_tech")],
        [hold("guidance", "gp", 0, distribution_pct=25), hold("gp", "au_tech", 8, proposed=True)],
        "gp", "au_tech",
    )
    assert not d.notifiable
    assert any("Guidance Note 23" in r for r in d.review)


def test_5_percent_with_a_business_arrangement():
    d = decide(
        [sge("soe", "CN"), corp("au")], [hold("soe", "au", 5, proposed=True)],
        "soe", "au", business_arrangement=True,
    )
    assert d.direct_interest.startswith("FATR s 16(b)")
    assert d.notifiable


def test_existing_stakes_in_the_group_count_towards_10_percent():
    # The SOE already holds 6%; a Ganzhou SASAC fund (same country) holds 5%.
    # Buying 1% more takes the group to 12%.
    d = decide(
        [sge("soe", "CN"), gov("gz", "CN"), corp("au")],
        [hold("soe", "au", 6), hold("gz", "au", 5), hold("soe", "au", 1, proposed=True)],
        "soe", "au",
    )
    assert d.before.pct == 11
    assert d.after.pct == 12
    assert any("already held a direct interest" in r for r in d.review)


def test_t17_new_wholly_owned_subsidiary_exception():
    d = decide(
        [sge("lgfv", "CN"), corp("syd_sub")], [hold("lgfv", "syd_sub", 100, proposed=True)],
        "lgfv", "syd_sub", new_wholly_owned_subsidiary=True,
    )
    assert not d.notifiable
    assert d.exceptions[0].startswith("FATR s 56(3)")


def test_t17_starting_a_business_is_notifiable_at_any_size():
    d = decide([sge("lgfv", "CN")], [], "lgfv", action="start_business")
    assert d.notifiable
    assert d.triggers[0].startswith("FATR s 56(1)(b)")


def test_a_private_buyer_is_outside_s_56():
    d = decide([corp("private"), corp("au")], [hold("private", "au", 30, proposed=True)], "private", "au")
    assert not d.buyer_is_fgi
    assert not d.notifiable
