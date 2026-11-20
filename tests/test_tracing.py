"""Tests for step 5: tracing under FATA s 19.

Case numbers refer to the test list in the rules document.
"""

import pytest

from firb_tracer.fgi import determine_fgi
from firb_tracer.model import from_dict
from firb_tracer.tracing import trace_interest

from test_fgi import corp, gov, hold, sge


def trace(entities, holdings, person, target):
    graph = from_dict({"entities": entities, "holdings": holdings})
    return trace_interest(graph, determine_fgi(graph), person, target)


def test_t09_full_attribution_not_multiplication():
    # SASAC 25% of Holdco, Holdco 12% of T: SASAC holds 12% of T, not 3%.
    r = trace(
        [gov("sz", "CN"), corp("holdco"), corp("t")],
        [hold("sz", "holdco", 25), hold("holdco", "t", 12)],
        "sz", "t",
    )
    assert r.pct == 12
    assert "holdco" in r.blocks


def test_t10_cliff_at_19_percent_nothing_is_traced():
    r = trace(
        [gov("sz", "CN"), corp("holdco"), corp("t")],
        [hold("sz", "holdco", 19), hold("holdco", "t", 60)],
        "sz", "t",
    )
    assert r.pct == 0  # not 19% x 60% = 11.4%


def test_t10_variant_a_2_percent_soe_tips_it_to_the_full_60():
    r = trace(
        [gov("sz", "CN"), sge("central_soe", "CN"), corp("holdco"), corp("t")],
        [hold("sz", "holdco", 19), hold("central_soe", "holdco", 2), hold("holdco", "t", 60)],
        "sz", "t",
    )
    assert r.pct == 60


def test_t11_the_same_block_is_counted_once():
    # A's 10% reaches SASAC by tracing and as an associate: 15%, not 25%.
    r = trace(
        [gov("sz", "CN"), corp("a"), corp("t")],
        [hold("sz", "a", 30), hold("a", "t", 10), hold("sz", "t", 5)],
        "sz", "t",
    )
    assert r.pct == 15
    assert r.blocks == {"sz": 5, "a": 10}


def test_attribution_runs_up_a_chain():
    r = trace(
        [gov("sz", "CN"), corp("a"), corp("b"), corp("t")],
        [hold("sz", "a", 20), hold("a", "b", 20), hold("b", "t", 15)],
        "sz", "t",
    )
    assert r.pct == 15


def test_two_routes_add_up_to_cross_the_threshold():
    # A private buyer: 30% of A and of B; A and B hold 12% and 10% of H.
    # Traced, the buyer holds 22% of H, so H's 50% of T is attributed.
    r = trace(
        [corp("buyer"), corp("a"), corp("b"), corp("h"), corp("t")],
        [hold("buyer", "a", 30), hold("buyer", "b", 30),
         hold("a", "h", 12), hold("b", "h", 10), hold("h", "t", 50)],
        "buyer", "t",
    )
    assert r.pct == 50
    assert any("s 19(3)" in n for n in r.notes)  # a private buyer: flagged


def test_cross_holdings_do_not_loop_forever():
    r = trace(
        [gov("sz", "CN"), corp("a"), corp("b"), corp("t")],
        [hold("sz", "a", 30), hold("a", "b", 30), hold("b", "a", 30), hold("b", "t", 8)],
        "sz", "t",
    )
    assert r.pct == pytest.approx(8)
