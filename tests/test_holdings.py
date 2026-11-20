"""Tests for step 2: each holder's own percentage (FATA s 17, s 18, s 22(4)).

Case numbers refer to the test list in the rules document.
"""

import pytest

from firb_tracer.holdings import (
    DISCRETIONARY,
    DISTRIBUTION,
    RIGHTS,
    SECURITIES,
    VETO,
    VOTING,
    effective_holding,
)
from firb_tracer.model import EntityKind, FutureRight, Holding, RightMode, RightType
from firb_tracer.thresholds import SUBSTANTIAL, meets

CORP = EntityKind.CORPORATION


def holding(**kwargs):
    return Holding(holder="h", held="t", **kwargs)


def right(pct, mode, type_=RightType.CONVERTIBLE):
    return FutureRight(type=type_, mode=mode, pct=pct)


def test_t01_exactly_20_percent_is_substantial():
    eh = effective_holding(holding(shares_pct=20), CORP)
    assert eh.pct == 20
    assert meets(eh.pct, SUBSTANTIAL)


def test_19_9_percent_is_not_substantial():
    assert not meets(effective_holding(holding(shares_pct=19.9), CORP).pct, SUBSTANTIAL)


def test_t02_transfer_right_adds_without_dilution():
    # 10% now, a right to acquire a further 12% of existing shares: 22%.
    eh = effective_holding(holding(shares_pct=10, future_rights=[right(12, RightMode.TRANSFER)]), CORP)
    assert eh.pct == pytest.approx(22)
    assert eh.basis == RIGHTS
    assert meets(eh.pct, SUBSTANTIAL)


def test_t02_variant_new_issue_dilutes_and_falls_short():
    # Same 12%, but by new issue: 22 / 112 = 19.64%. The mode decides the case.
    eh = effective_holding(holding(shares_pct=10, future_rights=[right(12, RightMode.ISSUE)]), CORP)
    assert eh.pct == pytest.approx(22 / 112 * 100)
    assert not meets(eh.pct, SUBSTANTIAL)


def test_new_issue_landing_exactly_on_20_percent():
    # No shares now, a right to 25 new shares per 100 issued: 25 / 125 = 20%.
    eh = effective_holding(holding(shares_pct=0, future_rights=[right(25, RightMode.ISSUE)]), CORP)
    assert meets(eh.pct, SUBSTANTIAL)


def test_several_rights_are_exercised_together():
    rights = [right(5, RightMode.TRANSFER), right(10, RightMode.ISSUE)]
    eh = effective_holding(holding(shares_pct=10, future_rights=rights), CORP)
    assert eh.pct == pytest.approx((10 + 5 + 10) / 110 * 100)


def test_put_obligation_is_not_counted_but_flagged():
    put = right(30, RightMode.TRANSFER, RightType.PUT_OBLIGATION)
    eh = effective_holding(holding(shares_pct=10, future_rights=[put]), CORP)
    assert eh.pct == 10
    assert any("R20" in n for n in eh.notes)


def test_t12_veto_lifts_5_percent_to_20():
    eh = effective_holding(holding(shares_pct=5, veto=True), CORP)
    assert eh.pct == 20
    assert eh.basis == VETO
    assert meets(eh.pct, SUBSTANTIAL)


def test_t21_veto_does_not_lower_a_larger_holding():
    eh = effective_holding(holding(shares_pct=25, veto=True), CORP)
    assert eh.pct == 25
    assert eh.basis == SECURITIES


def test_voting_power_above_shares_wins():
    eh = effective_holding(holding(shares_pct=10, voting_pct=30), CORP)
    assert eh.pct == 30
    assert eh.basis == VOTING


def test_t13_distribution_entitlement_in_a_partnership():
    # A guidance fund LP with 25% of distributions and no say in management.
    eh = effective_holding(holding(distribution_pct=25), EntityKind.GENERAL_PARTNER)
    assert eh.pct == 25
    assert eh.basis == DISTRIBUTION


def test_t16_discretionary_trust_counts_the_maximum():
    eh = effective_holding(holding(shares_pct=0, distribution_pct=5, max_distribution_pct=100), EntityKind.TRUSTEE)
    assert eh.pct == 100
    assert eh.basis == DISCRETIONARY


def test_distribution_figures_are_ignored_for_a_company():
    eh = effective_holding(holding(shares_pct=5, distribution_pct=50), CORP)
    assert eh.pct == 5
    assert any("ignored" in n for n in eh.notes)


def test_every_measure_is_kept_for_the_report():
    eh = effective_holding(holding(shares_pct=5, veto=True, future_rights=[right(3, RightMode.TRANSFER)]), CORP)
    assert set(eh.measures) == {SECURITIES, VOTING, VETO, RIGHTS}
