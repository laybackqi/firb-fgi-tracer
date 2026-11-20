"""Step 3 of the decision flow: who is an associate of whom (FATA s 6).

Association is worked out from ONE person's point of view: s 17(1) adds up a
person's holding "together with one or more associates" of THAT person.
Association is not transitive, so an associate of an associate is not
automatically an associate.

Grounds applied in v0.1:

* s 6(1)(l): foreign governments, separate government entities and foreign
  government investors of the same country (any tier) are associates of one
  another (R6). Not for an investor caught only by the 40% multi-country test
  (FATR s 45(5), R7).
* s 6(1)(f) and (g): an entity whose senior officers act on a person's wishes,
  and that person, are associates (R8).
* s 6(1)(b): persons acting in concert, across countries too (R9).

Grounds left out of v0.1, and why:

* s 6(1)(h), (i) and (k) (holding a substantial interest): any entity in which
  a government holds a substantial interest is itself a foreign government
  investor, so it is already an associate of that government under (l)(iii).
  For the questions this tool answers, these grounds add nothing.
* s 6(1)(c) (partners): a passive limited partner is excluded by s 6(3)(h),
  and a general partner's position is captured by s 17(1)(d) (R23).

This module is kept separate so that it can be replaced if the associate
rules are amended (the 2026 reform proposals would extend them to lenders).
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import OwnershipGraph


@dataclass(frozen=True)
class Association:
    """One associate of a person, and the ground for it."""

    other: str
    ground: str


@dataclass(frozen=True)
class GovProfile:
    """What s 6(1)(l) needs to know about a person.

    countries: the countries the person is a government, SGE or investor of.
    in_l: False for an investor caught only by the 40% test (FATR s 45(5)).
    """

    countries: frozenset[str]
    in_l: bool


def associates_of(
    person: str,
    graph: OwnershipGraph,
    profiles: dict[str, GovProfile],
) -> list[Association]:
    """Every associate of `person` under the grounds above.

    `profiles` holds every foreign government, SGE and foreign government
    investor known so far, so the result grows as more investors are found.
    """
    found: dict[str, str] = {}

    def add(other: str, ground: str) -> None:
        if other != person and other not in found:
            found[other] = ground

    # s 6(1)(l): same-country governments and investors.
    mine = profiles.get(person)
    if mine is not None and mine.in_l:
        for other, theirs in sorted(profiles.items()):
            if theirs.in_l and mine.countries & theirs.countries:
                kind = graph.entities[other].gov_status.value if graph.entities[other].is_government else "FGI"
                para = {"FG": "(l)(i)", "SGE": "(l)(ii)"}.get(kind, "(l)(iii)")
                shared = ", ".join(sorted(mine.countries & theirs.countries))
                add(other, f"FATA s 6(1){para}: {kind} in relation to {shared}")

    # s 6(1)(f) and (g): officers who act on someone's wishes.
    for entity in graph.entities.values():
        if person in entity.acts_on_wishes_of:
            add(entity.id, "FATA s 6(1)(f): its senior officers act on this person's wishes")
    for other in graph.entities[person].acts_on_wishes_of:
        add(other, "FATA s 6(1)(g): this entity's senior officers act on that person's wishes")

    # s 6(1)(b): acting in concert, recorded on any holding.
    for h in graph.holdings:
        if h.holder == person:
            for other in h.concert_with:
                add(other, "FATA s 6(1)(b): acting in concert")
        elif person in h.concert_with:
            add(h.holder, "FATA s 6(1)(b): acting in concert")

    return [Association(other, ground) for other, ground in found.items()]
