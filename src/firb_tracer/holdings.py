"""Step 2 of the decision flow: the percentage each holder holds in each entity.

FATA s 17(1) says a person holds an interest of a specified percentage if the
person, alone or with associates, can control that percentage of voting power,
holds that percentage of issued securities, or would hold it if rights were
exercised. Any one of these is enough, so the holding is the HIGHEST of the
measures (rule R3).

This module works out each holder's own percentage, edge by edge. Associates
are added later (associates.py); tracing through intermediate entities comes
later still (tracing.py).

Each holder is measured separately and percentages are never normalised: if A
holds 60% and B has an option over A's shares, both A and B can hold 60% (R20).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import EntityKind, Holding, OwnershipGraph, RightMode, RightType
from .thresholds import VETO_DEEMED

# Labels for the basis of each measure, used in reports.
SECURITIES = "issued securities (FATA s 17(1)(b))"
VOTING = "voting power (FATA s 17(1)(a))"
VETO = "potential voting power deemed by a veto (FATA s 22(4))"
RIGHTS = "securities if rights were exercised (FATA s 17(1)(c), s 18(2))"
DISTRIBUTION = "distribution entitlement (FATA s 11A, s 17(2A))"
DISCRETIONARY = "maximum discretionary distribution (FATA s 18(3))"


@dataclass
class EffectiveHolding:
    """One holder's percentage in one entity, with how it was reached."""

    holder: str
    held: str
    pct: float  # the highest measure: the figure the law uses
    basis: str  # which measure produced pct
    measures: dict[str, float] = field(default_factory=dict)  # every measure computed
    notes: list[str] = field(default_factory=list)  # assumptions and points for review

    def limbs(self) -> dict[str, float]:
        """This holding under each limb of s 17(1), for adding up a group.

        When associates' holdings are combined, each limb is added up
        separately and the group takes the highest total: votes are added to
        votes and securities to securities, never one holder's votes to
        another's securities.
        """
        m = self.measures
        securities = m.get(SECURITIES, 0.0)
        return {
            LIMB_VOTING: max(m.get(VOTING, 0.0), m.get(VETO, 0.0)),
            LIMB_SECURITIES: securities,
            LIMB_RIGHTS: m.get(RIGHTS, securities),
            LIMB_DISTRIBUTION: max(m.get(DISTRIBUTION, 0.0), m.get(DISCRETIONARY, 0.0)),
        }


# The limbs used when adding up a group of associates.
LIMB_VOTING = "voting or potential voting power (FATA s 17(1)(a), s 22(4))"
LIMB_SECURITIES = "issued securities (FATA s 17(1)(b))"
LIMB_RIGHTS = "securities if rights were exercised (FATA s 17(1)(c), s 18(2))"
LIMB_DISTRIBUTION = "distribution entitlement (FATA s 11A, s 17(2A), s 18(3))"


def after_exercise(shares_pct: float, rights: list) -> float:
    """Percentage of issued securities held if every right were exercised.

    Rights to acquire existing securities (TRANSFER) add to the holder's share
    but leave the total unchanged. Rights to new securities (ISSUE) add to both
    the holder's share and the total, which dilutes everyone (R20).

    All right percentages are measured against issued securities BEFORE
    exercise, so they can be added together.
    """
    transferred = sum(r.pct for r in rights if r.mode is RightMode.TRANSFER)
    issued = sum(r.pct for r in rights if r.mode is RightMode.ISSUE)
    held_after = shares_pct + transferred + issued
    total_after = 100.0 + issued
    return min(100.0, held_after / total_after * 100.0)


def effective_holding(h: Holding, held_kind: EntityKind) -> EffectiveHolding:
    """Work out the highest of the s 17(1) measures for one holding."""
    measures: dict[str, float] = {}
    notes: list[str] = []

    # s 17(1)(b): issued securities.
    measures[SECURITIES] = h.shares_pct

    # s 17(1)(a): voting power. Without a separate figure, one vote per share.
    if h.voting_pct is not None:
        measures[VOTING] = h.voting_pct
    elif h.shares_pct > 0:
        measures[VOTING] = h.shares_pct
        notes.append("voting power assumed equal to shareholding (one vote per share)")

    # s 22(4): a veto over any resolution is 20% of potential voting power.
    # Broad reading, confirmed 2026-11-11 (R15).
    if h.veto:
        measures[VETO] = VETO_DEEMED
        notes.append("veto deemed 20% of potential voting power on the broad reading of 'any resolution' (R15)")

    # s 17(1)(c) and s 18(2): rights to acquire are assumed to be exercised.
    # An obligation to buy under someone else's put is left to human judgment (R20).
    rights = [r for r in h.future_rights if r.type is not RightType.PUT_OBLIGATION]
    if rights:
        measures[RIGHTS] = after_exercise(h.shares_pct, rights)
    if len(rights) < len(h.future_rights):
        notes.append("obligation to buy under a put option not counted; needs human judgment (R20)")

    # Trusts and limited partnerships: distribution entitlements count.
    if held_kind in (EntityKind.TRUSTEE, EntityKind.GENERAL_PARTNER):
        if h.distribution_pct is not None:
            measures[DISTRIBUTION] = h.distribution_pct
        if h.max_distribution_pct is not None:
            measures[DISCRETIONARY] = h.max_distribution_pct
    elif h.distribution_pct is not None or h.max_distribution_pct is not None:
        notes.append("distribution figures ignored: they apply only to trusts and limited partnerships")

    basis, pct = max(measures.items(), key=lambda item: item[1])
    return EffectiveHolding(h.holder, h.held, min(pct, 100.0), basis, measures, notes)


def effective_holdings(graph: OwnershipGraph) -> list[EffectiveHolding]:
    """Effective holdings for every edge in the graph, in input order."""
    return [effective_holding(h, graph.entities[h.held].kind) for h in graph.holdings]
