"""Step 6 of the decision flow: must the action be notified? (FATR s 16, s 56)

For a foreign government investor the monetary threshold is nil (R21). Under
FATR s 56(1) each of these is a significant and notifiable action:

  (a) acquiring a direct interest in an Australian entity or business;
  (b) starting an Australian business;
  (c) acquiring (i) an interest in a tenement, or (ii) an interest of at
      least 10% in a mining, production or exploration entity;

subject to the exceptions in s 56(3)-(7) (R22).

A direct interest (FATR s 16) is an interest of at least 10%; or at least 5%
with a legal arrangement relating to the businesses; or any interest that puts
the holder in a position to influence or participate in central management
and control, or to influence or determine policy.

The engine compares the buyer group's traced interest in the target before
and after the holdings marked `proposed`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .fgi import Finding, determine_fgi
from .model import Action, OwnershipGraph, Transaction
from .thresholds import DIRECT, DIRECT_WITH_ARRANGEMENT, meets
from .tracing import TraceResult, trace_interest

GN23_NOTE = (
    "Holdings by other government investors of the same country count towards "
    "these percentages (FATA s 6(1)(l)) but cannot be seen in this structure. "
    "Check the target's substantial holder notices, top-20 holder lists and "
    "share register before relying on this result (Guidance Note 23, R11)."
)


@dataclass
class Decision:
    """The answer to: must this action be notified?"""

    notifiable: bool
    buyer_is_fgi: bool
    reasoning: list[str] = field(default_factory=list)  # the chain, in order
    triggers: list[str] = field(default_factory=list)  # provisions that apply
    exceptions: list[str] = field(default_factory=list)  # exceptions applied
    review: list[str] = field(default_factory=list)  # points for human judgment
    buyer_finding: Finding | None = None
    before: TraceResult | None = None
    after: TraceResult | None = None
    direct_interest: str = ""  # the limb of s 16 met after the action, if any


def direct_interest(graph: OwnershipGraph, trace: TraceResult, tx: Transaction) -> str:
    """Which limb of FATR s 16 the traced interest meets, or '' if none."""
    if meets(trace.pct, DIRECT):
        return f"FATR s 16(a): an interest of {trace.pct:g}%, at least 10%"
    if tx.business_arrangement and meets(trace.pct, DIRECT_WITH_ARRANGEMENT):
        return f"FATR s 16(b): an interest of {trace.pct:g}% with a related business arrangement"
    if trace.pct > 0:
        for h in graph.holders_of(trace.target):
            if h.holder in trace.attributed and (h.management_influence or h.board_seats):
                why = "a board seat" if h.board_seats else "influence over management or policy"
                return f"FATR s 16(c): an interest of {trace.pct:g}% with {why}"
    return ""


def assess(graph: OwnershipGraph) -> Decision:
    """Assess the transaction described in the graph."""
    tx = graph.transaction or Transaction()
    buyer = graph.buyer
    if buyer is None:
        raise ValueError("the structure must name a buyer")

    findings = determine_fgi(graph)
    finding = findings.get(buyer)
    is_fgi = finding is not None and finding.is_fgi
    d = Decision(notifiable=False, buyer_is_fgi=is_fgi, buyer_finding=finding)

    if not is_fgi:
        d.reasoning.append(
            "The buyer is not a foreign government investor, so FATR s 56 does not apply. "
            "Other notification thresholds under the FATA are outside this tool."
        )
        return d
    d.reasoning.append(f"The buyer is a foreign government investor: {finding.provision}.")

    if tx.action is Action.START_BUSINESS:
        d.triggers.append("FATR s 56(1)(b): starting an Australian business")
        d.review.append(
            "Confirm the activity is a new business, not an incidental expansion of an existing "
            "one in the same ANZSIC division (FATA s 8B)."
        )
        d.notifiable = True
        return d

    if tx.action is Action.ACQUIRE_TENEMENT:
        d.triggers.append("FATR s 56(1)(c)(i): acquiring an interest in a tenement")
        d.notifiable = True
        return d

    # Acquiring an interest: compare the traced interest before and after.
    target = graph.target
    if target is None:
        raise ValueError("an acquisition must name a target")
    if not any(h.proposed for h in graph.holdings):
        d.review.append("No holding is marked as proposed, so before and after are the same.")

    before_graph = graph.without_proposed()
    d.before = trace_interest(before_graph, determine_fgi(before_graph), buyer, target)
    d.after = trace_interest(graph, findings, buyer, target)
    d.reasoning.append(
        f"With associates and by tracing (FATA s 17, s 19), the buyer's interest in the target "
        f"goes from {d.before.pct:g}% to {d.after.pct:g}%."
    )

    d.direct_interest = direct_interest(graph, d.after, tx)
    had_direct = bool(direct_interest(before_graph, d.before, tx))

    # s 56(1)(a): acquiring a direct interest in an Australian entity.
    if tx.target_is_australian and d.direct_interest:
        d.reasoning.append(f"After the action the buyer holds a direct interest: {d.direct_interest}.")
        exception = ""
        if tx.new_wholly_owned_subsidiary:
            exception = "FATR s 56(3): the interest is acquired by establishing a new wholly-owned subsidiary"
        elif tx.offshore_non_material:
            exception = "FATR s 56(4): a non-material interest acquired through a foreign entity (user confirms (a)-(d))"
        elif tx.consortium_initial_interest:
            exception = "FATR s 56(5): initial interest in an entity set up by a consortium for a later notifiable acquisition"
        elif tx.passive_increase and had_direct:
            exception = "FATR s 56(6): a passive increase under FATA s 18A, with a direct interest held before"
        if exception:
            d.exceptions.append(exception)
        else:
            d.triggers.append("FATR s 56(1)(a): acquiring a direct interest in an Australian entity")
            if had_direct:
                d.review.append(
                    "The buyer already held a direct interest before this action; confirm how "
                    "s 56(1)(a) applies to a further acquisition."
                )
    elif tx.target_is_australian:
        d.reasoning.append("After the action the buyer does not hold a direct interest (FATR s 16).")

    # s 56(1)(c)(ii): 10% of a mining, production or exploration entity.
    if tx.target_is_mining_entity and meets(d.after.pct, DIRECT):
        if tx.passive_increase and meets(d.before.pct, DIRECT):
            d.exceptions.append("FATR s 56(7): a passive increase, with 10% or more held before")
        else:
            d.triggers.append(
                "FATR s 56(1)(c)(ii): acquiring an interest of at least 10% in a mining, "
                "production or exploration entity"
            )

    d.notifiable = bool(d.triggers)
    d.review.append(GN23_NOTE)
    d.review.extend(d.after.notes)
    return d
