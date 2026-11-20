"""Step 5 of the decision flow: the group's interest in the target (FATA s 19).

Section 19 attributes upwards. A person who holds a substantial interest (at
least 20%) in a "higher party" is taken to hold the interests the higher
party holds in a "lower party", in full (R12). Below 20%, nothing is
attributed (R13). The section applies again on top of its own results, so
attribution runs up a chain of any length.

For actions by foreign government investors, s 19 always applies: the
exclusions in s 19(3) are switched off by FATR s 48 (R16).

How the engine does it:

1. Start with the person and its associates (associates.py).
2. Add every entity in which that set, taken together, holds at least 20%.
   Traced interests count, so repeat until nothing new is added. Two routes
   of 12% and 10% into the same entity add up to 22%.
3. The interest in the target is the sum of the direct holdings in the
   target by the members of that final set. Each holding is one block of
   shares and is counted once, however many routes lead to it (R14).

This module is kept separate so that it can be replaced if s 19 is amended
(the 2026 reform proposals target the full-attribution result).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .associates import associates_of
from .fgi import Finding, _index, gov_profiles, group_interest
from .holdings import effective_holdings
from .model import OwnershipGraph
from .thresholds import SUBSTANTIAL, meets


@dataclass
class TraceResult:
    """A person's interest in a target, with the route to it."""

    person: str
    target: str
    pct: float
    limb: str
    # Everyone whose holdings in the target count, and why.
    attributed: dict[str, str] = field(default_factory=dict)
    # The blocks of target shares counted: holder -> that holder's percentage.
    blocks: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def trace_interest(
    graph: OwnershipGraph,
    findings: dict[str, Finding],
    person: str,
    target: str,
) -> TraceResult:
    """The interest `person`, with associates and by tracing, holds in `target`."""
    index = _index(effective_holdings(graph))
    profiles = gov_profiles(graph, findings)
    notes: list[str] = []

    # 1. The person and its associates.
    attributed: dict[str, str] = {person: "the person"}
    for a in associates_of(person, graph, profiles):
        attributed[a.other] = a.ground

    # 2. Every entity in which the set holds at least 20%, until stable.
    changed = True
    while changed:
        changed = False
        for entity_id in graph.entities:
            if entity_id == person or entity_id == target or entity_id not in index:
                continue
            if "FATA s 19" in attributed.get(entity_id, ""):
                continue
            pct, _ = group_interest([m for m in attributed if m != entity_id], index[entity_id])
            if meets(pct, SUBSTANTIAL):
                s19 = f"FATA s 19: the group holds {pct:g}% of it, so its holdings are attributed in full"
                if entity_id in attributed:
                    # Already an associate; record tracing as a second ground.
                    attributed[entity_id] = f"{s19}; also {attributed[entity_id]}"
                else:
                    attributed[entity_id] = s19
                    changed = True

    # 3. Count each block of target shares once.
    held = index.get(target, {})
    members = [m for m in attributed if m in held]
    pct, limb = group_interest(members, held)
    blocks = {m: held[m].pct for m in members}

    finding = findings.get(person)
    if finding is None or not finding.is_fgi:
        notes.append(
            "the person is not a foreign government investor, so the exclusions in "
            "FATA s 19(3) may apply; this tool traces as if they do not"
        )
    return TraceResult(person, target, pct, limb, attributed, blocks, notes)
