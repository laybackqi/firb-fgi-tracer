"""Step 4 of the decision flow: which entities are foreign government investors.

FATR s 17(1) in brief:

  (a)       a foreign government or separate government entity;
  (b)-(d)   a corporation, trustee or general partner in which
            (i)  one government, with its associates, holds at least 20%, or
            (ii) governments of more than one country together hold at least 40%;
  (e)       the same tests again, reading "foreign government" as including a
            foreign government investor, applied as many times as needed.

The tests depend on each other. Whether two holders are associates under
FATA s 6(1)(l)(iii) depends on who is already an investor, and who is an
investor depends on associates' holdings being added up. So the engine runs in
rounds: each round tests every entity against the investors found so far, and
the rounds stop when a round finds nobody new (rules document, step 4).
Percentages are never multiplied along a chain (R4).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .associates import GovProfile, associates_of
from .holdings import VETO, EffectiveHolding, effective_holdings
from .model import EntityKind, OwnershipGraph
from .thresholds import AGGREGATE_SUBSTANTIAL, SUBSTANTIAL, meets

# The paragraph of s 17(1) for each kind of holder.
_PARA = {
    EntityKind.CORPORATION: "(b)",
    EntityKind.TRUSTEE: "(c)",
    EntityKind.GENERAL_PARTNER: "(d)",
}


@dataclass
class Finding:
    """The engine's conclusion about one entity."""

    entity: str
    is_fgi: bool
    provision: str  # e.g. "FATR s 17(1)(b)(i)"
    countries: frozenset[str]
    pct: float = 0.0  # the percentage that met the threshold
    limb: str = ""  # which limb of FATA s 17(1) produced pct
    via: str | None = None  # the government or investor taken as the holder (R10)
    members: dict[str, str] = field(default_factory=dict)  # holder -> why counted
    only_aggregate: bool = False  # caught only by the 40% test
    exemption: str = ""  # status of the s 17(2) exception, if relevant
    round: int = 0  # the round in which it was found (0 = a government itself)


def _merge(a: EffectiveHolding, b: EffectiveHolding) -> EffectiveHolding:
    """Combine two holdings by the same holder in the same entity.

    This happens when an existing stake and a proposed purchase are recorded
    as separate lines. Each measure is added up, then the highest is taken.
    """
    measures = {k: min(100.0, a.measures.get(k, 0.0) + b.measures.get(k, 0.0))
                for k in a.measures.keys() | b.measures.keys()}
    basis, pct = max(measures.items(), key=lambda item: item[1])
    return EffectiveHolding(a.holder, a.held, pct, basis, measures, a.notes + b.notes)


def _index(holdings: list[EffectiveHolding]) -> dict[str, dict[str, EffectiveHolding]]:
    """held -> holder -> effective holding (several lines by one holder are combined)."""
    index: dict[str, dict[str, EffectiveHolding]] = defaultdict(dict)
    for eh in holdings:
        earlier = index[eh.held].get(eh.holder)
        index[eh.held][eh.holder] = eh if earlier is None else _merge(earlier, eh)
    return index


def group_interest(members: list[str], held: dict[str, EffectiveHolding]) -> tuple[float, str]:
    """Add up the members' holdings limb by limb; return the best limb."""
    totals: dict[str, float] = defaultdict(float)
    for m in members:
        if m in held:
            for limb, pct in held[m].limbs().items():
                totals[limb] += pct
    if not totals:
        return 0.0, ""
    limb, pct = max(totals.items(), key=lambda item: item[1])
    return min(pct, 100.0), limb


def _profiles(graph: OwnershipGraph, findings: dict[str, Finding]) -> dict[str, GovProfile]:
    """Every government, SGE and investor known so far, for s 6(1)(l)."""
    profiles: dict[str, GovProfile] = {}
    for f in findings.values():
        if f.is_fgi:
            profiles[f.entity] = GovProfile(f.countries, in_l=not f.only_aggregate)
    return profiles


def gov_profiles(graph: OwnershipGraph, findings: dict[str, Finding]) -> dict[str, GovProfile]:
    """Public form of _profiles, for later steps that need s 6(1)(l)."""
    return _profiles(graph, findings)


def _test_single(entity_id: str, graph, held, findings, profiles, rnd) -> Finding | None:
    """Paragraphs (b)-(d)(i), and (e) read with them."""
    kind = graph.entities[entity_id].kind
    best: Finding | None = None
    for person in sorted(held):
        if person not in findings or not findings[person].is_fgi:
            continue  # only a government or investor can be the holder (R10)
        assoc = associates_of(person, graph, profiles)
        members = {person: "the holder"}
        members.update({a.other: a.ground for a in assoc if a.other in held})
        pct, limb = group_interest(list(members), held)
        if not meets(pct, SUBSTANTIAL):
            continue
        holder = findings[person]
        if graph.entities[person].is_government:
            provision = f"FATR s 17(1){_PARA[kind]}(i)"
        else:
            # (e)(i): the holder is an investor under (b)-(d);
            # (e)(ii): the holder is an investor because of an earlier (e).
            sub = "(ii)" if "(e)" in holder.provision else "(i)"
            provision = f"FATR s 17(1)(e){sub}, read with {_PARA[kind]}(i)"
        countries = set(holder.countries)
        for m in members:
            if m in findings and findings[m].is_fgi and not findings[m].only_aggregate:
                countries |= findings[m].countries
        candidate = Finding(
            entity_id, True, provision, frozenset(countries), pct, limb, person, members, round=rnd
        )
        # Prefer a government as the holder, then the higher percentage.
        rank = (graph.entities[person].is_government, pct)
        if best is None or rank > (graph.entities[best.via].is_government, best.pct):
            best = candidate
    return best


def _test_aggregate(entity_id: str, graph, held, findings, rnd) -> Finding | None:
    """Paragraphs (b)-(d)(ii): governments of more than one country, 40%."""
    kind = graph.entities[entity_id].kind
    members = {p: "government holder" for p in held if p in findings and findings[p].is_fgi}
    countries: set[str] = set()
    for p in members:
        countries |= findings[p].countries
    if len(countries) < 2:
        return None
    pct, limb = group_interest(list(members), held)
    if not meets(pct, AGGREGATE_SUBSTANTIAL):
        return None
    uses_investor = any(not graph.entities[p].is_government for p in members)
    provision = f"FATR s 17(1){_PARA[kind]}(ii)"
    if uses_investor:
        provision = f"FATR s 17(1)(e), read with {_PARA[kind]}(ii)"
    finding = Finding(
        entity_id, True, provision, frozenset(countries), pct, limb, None, members,
        only_aggregate=True, round=rnd,
    )
    # FATR s 17(2): the collective investment scheme exception (R5).
    vetoed = [p for p in members if VETO in held[p].measures]
    if vetoed:
        finding.exemption = "unavailable: a government member holds a veto, so s 17(2)(b)(iii) is not met"
    elif graph.entities[entity_id].fund_exemption_claimed:
        finding.is_fgi = False
        finding.exemption = "applied: caught only by the 40% test, and the user confirms s 17(2)(b)-(c)"
    else:
        finding.exemption = "possible: caught only by the 40% test; confirm the elements of s 17(2)(b)-(c)"
    return finding


def determine_fgi(graph: OwnershipGraph, max_rounds: int | None = None) -> dict[str, Finding]:
    """Run the rounds until no new investor is found. Returns findings by entity id.

    Governments appear with provision "FATR s 17(1)(a)". Entities caught only
    by the 40% test but exempted under s 17(2) appear with is_fgi False.
    Entities that are not investors and were never caught do not appear.
    """
    held_index = _index(effective_holdings(graph))
    findings: dict[str, Finding] = {}
    for e in graph.entities.values():
        if e.is_government:
            findings[e.id] = Finding(e.id, True, "FATR s 17(1)(a)", frozenset({e.country or "?"}))

    limit = max_rounds or len(graph.entities) + 1
    for rnd in range(1, limit + 1):
        snapshot = dict(findings)  # each round looks only at earlier rounds
        profiles = _profiles(graph, snapshot)
        new: dict[str, Finding] = {}
        for entity_id, entity in graph.entities.items():
            earlier = snapshot.get(entity_id)
            if earlier is not None and earlier.is_fgi:
                continue  # once an investor, always an investor
            if entity.kind not in _PARA or entity_id not in held_index:
                continue
            held = held_index[entity_id]
            finding = _test_single(entity_id, graph, held, snapshot, profiles, rnd)
            if finding is None:
                finding = _test_aggregate(entity_id, graph, held, snapshot, rnd)
            if finding is None:
                continue
            # An entity exempted earlier is re-tested, since new investors may
            # now bring it within (i); it counts as new only if that changes.
            if earlier is not None and (earlier.is_fgi, earlier.provision) == (finding.is_fgi, finding.provision):
                continue
            new[entity_id] = finding
        if not new:
            break
        findings.update(new)
    return findings
