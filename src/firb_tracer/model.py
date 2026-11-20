"""Data model for the ownership graph.

This module covers steps 0 and 1 of the decision flow in docs/rules.md.

* Entities are the nodes of the graph. Each one carries the user's own
  characterisation of it as a foreign government (FG) or a separate
  government entity (SGE) under s 4 of the FATA. The tool records that
  judgment; it never makes it (rule R1).
* Holdings are the edges. Each one records the raw facts that later modules
  need to work out an "interest of a specified percentage" (FATA s 17):
  shares, votes, distribution entitlements, future rights and vetoes.

Trustees and general partners are modelled by capacity: one company acting as
trustee of two different trusts is two separate nodes (rule R24).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class GovStatus(str, Enum):
    """The user's characterisation of an entity under FATA s 4 (rule R1)."""

    FG = "FG"  # foreign government: paras (a)-(c) of the definition
    SGE = "SGE"  # separate government entity
    NONE = "none"  # neither
    UNCERTAIN = "uncertain"  # needs human judgment; reported, never guessed


class EntityKind(str, Enum):
    """What sort of person the node is."""

    GOVERNMENT = "government"  # a body politic or part of one, e.g. a SASAC
    CORPORATION = "corporation"
    TRUSTEE = "trustee"  # a trustee acting for ONE specific trust (R24)
    GENERAL_PARTNER = "general_partner"  # a GP acting for ONE specific ULP (R24)
    INDIVIDUAL = "individual"


class RightType(str, Enum):
    """Rights that may change a percentage (FATA s 15, s 17(1)(c), s 18)."""

    CALL_OPTION = "call_option"
    CONVERTIBLE = "convertible"
    SUBSCRIPTION = "subscription"
    # The other side of a put option: an obligation to buy. Whether this is an
    # "agreement to acquire" under s 15(1)(a) is left to human judgment (R20).
    PUT_OBLIGATION = "put_obligation"


class RightMode(str, Enum):
    """How the securities would be obtained (R20)."""

    TRANSFER = "transfer"  # existing securities change hands: denominator unchanged
    ISSUE = "issue"  # new securities are issued: denominator grows


# --------------------------------------------------------------------------
# Nodes and edges
# --------------------------------------------------------------------------


@dataclass
class FutureRight:
    """A right that, if exercised, would give the holder more securities."""

    type: RightType
    mode: RightMode
    # Securities obtainable on exercise, as a percentage of the issued
    # securities BEFORE exercise. The holdings module adjusts the denominator
    # when mode is ISSUE.
    pct: float
    counterparty: str | None = None
    note: str = ""


@dataclass
class Entity:
    """A node: any person that holds, or is held."""

    id: str
    name: str
    kind: EntityKind
    country: str | None = None  # ISO code, e.g. "CN"; required for FG and SGE
    gov_status: GovStatus = GovStatus.NONE
    gov_reason: str = ""  # why the user characterised it this way
    capacity_of: str | None = None  # the trust or ULP, for TRUSTEE and GENERAL_PARTNER
    # FATA s 6(1)(f): this entity's senior officers act on these persons' wishes.
    # Filling this in makes them associates (R8).
    acts_on_wishes_of: list[str] = field(default_factory=list)
    # Evidence of non-equity control, e.g. "party_committee_pre_review".
    # On their own these only trigger a prompt for human review (R8).
    control_indicators: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def is_government(self) -> bool:
        """True for a foreign government or separate government entity."""
        return self.gov_status in (GovStatus.FG, GovStatus.SGE)


@dataclass
class Holding:
    """An edge: what one person holds in another, with its source."""

    holder: str
    held: str
    shares_pct: float = 0.0  # issued securities, FATA s 17(1)(b)
    voting_pct: float | None = None  # voting power if different, s 17(1)(a)
    distribution_pct: float | None = None  # trusts and ULPs, s 11A, s 17(2A)
    max_distribution_pct: float | None = None  # discretionary trusts, s 18(3)
    future_rights: list[FutureRight] = field(default_factory=list)
    veto: bool = False  # s 22(4): deemed 20% of potential voting power (R15)
    veto_scope: str = ""
    board_seats: str = ""  # e.g. "1/5"
    management_influence: bool = False  # FATR s 16(c), relevant to the target only
    concert_with: list[str] = field(default_factory=list)  # FATA s 6(1)(b)
    source: str = ""  # primary source of the figures (R18)


@dataclass
class Issue:
    """A problem found by validation."""

    level: str  # "error" stops the analysis; "warning" goes into the report
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.message}"


@dataclass
class OwnershipGraph:
    """The whole structure: entities, holdings and the parties of interest."""

    title: str
    entities: dict[str, Entity]
    holdings: list[Holding]
    buyer: str | None = None  # the acquirer, for the notification test
    target: str | None = None  # the Australian target, for the notification test

    def holders_of(self, entity_id: str) -> list[Holding]:
        """Holdings IN this entity (who sits above it)."""
        return [h for h in self.holdings if h.held == entity_id]

    def holdings_of(self, entity_id: str) -> list[Holding]:
        """Holdings BY this entity (what sits below it)."""
        return [h for h in self.holdings if h.holder == entity_id]

    def validate(self) -> list[Issue]:
        """Check the input before any legal analysis runs."""
        issues: list[Issue] = []
        ids = set(self.entities)

        def err(msg: str) -> None:
            issues.append(Issue("error", msg))

        def warn(msg: str) -> None:
            issues.append(Issue("warning", msg))

        for party, role in ((self.buyer, "buyer"), (self.target, "target")):
            if party is not None and party not in ids:
                err(f"{role} '{party}' is not a listed entity")

        for e in self.entities.values():
            if e.is_government and not e.country:
                err(f"{e.id}: a {e.gov_status.value} must have a country (needed for FATA s 6(1)(l))")
            if e.is_government and not e.gov_reason:
                warn(f"{e.id}: no reason given for characterising it as {e.gov_status.value} (R1)")
            if e.gov_status is GovStatus.UNCERTAIN:
                warn(f"{e.id}: government status is uncertain and needs human characterisation (R1)")
            if e.kind in (EntityKind.TRUSTEE, EntityKind.GENERAL_PARTNER) and not e.capacity_of:
                err(f"{e.id}: a {e.kind.value} node must name the trust or partnership it acts for (R24)")
            for other in e.acts_on_wishes_of:
                if other not in ids:
                    err(f"{e.id}: acts_on_wishes_of refers to unknown entity '{other}'")
            if e.control_indicators and not e.acts_on_wishes_of:
                warn(f"{e.id}: non-equity control indicators present but no controller named; review s 6(1)(f) (R8)")

        totals: dict[str, float] = {}
        for h in self.holdings:
            where = f"{h.holder} -> {h.held}"
            if h.holder not in ids:
                err(f"{where}: unknown holder '{h.holder}'")
            if h.held not in ids:
                err(f"{where}: unknown held entity '{h.held}'")
            if h.holder == h.held:
                err(f"{where}: an entity cannot hold itself")
            for name in ("shares_pct", "voting_pct", "distribution_pct", "max_distribution_pct"):
                value = getattr(h, name)
                if value is not None and not 0 <= value <= 100:
                    err(f"{where}: {name} must be between 0 and 100, got {value}")
            for r in h.future_rights:
                if r.pct <= 0:
                    err(f"{where}: a future right must cover more than 0%")
                if r.type is RightType.PUT_OBLIGATION:
                    warn(f"{where}: obligation to buy under a put option needs human judgment (R20)")
            for other in h.concert_with:
                if other not in ids:
                    err(f"{where}: concert_with refers to unknown entity '{other}'")
            if h.veto:
                warn(f"{where}: veto counted as 20% of potential voting power on the broad reading of s 22(4) (R15)")
            if not h.source:
                warn(f"{where}: no source given for these figures (R18)")
            totals[h.held] = totals.get(h.held, 0.0) + h.shares_pct

        for held, total in totals.items():
            if total > 100.0001:
                err(f"{held}: issued shares held add up to {total:g}%, more than 100%")

        return issues


# --------------------------------------------------------------------------
# Loading from YAML
# --------------------------------------------------------------------------


class InputError(ValueError):
    """The input file does not match the expected shape."""


def _check_keys(raw: dict[str, Any], cls: type, where: str) -> None:
    """Reject unknown keys, so a typo such as 'share_pct' is caught."""
    allowed = {f.name for f in fields(cls)}
    unknown = set(raw) - allowed
    if unknown:
        raise InputError(f"{where}: unknown field(s) {sorted(unknown)}; allowed: {sorted(allowed)}")


def _enum(cls: type[Enum], value: Any, where: str) -> Any:
    try:
        return cls(value)
    except ValueError:
        options = [m.value for m in cls]  # type: ignore[attr-defined]
        raise InputError(f"{where}: '{value}' is not one of {options}") from None


def _entity(raw: dict[str, Any]) -> Entity:
    where = f"entity '{raw.get('id', '?')}'"
    _check_keys(raw, Entity, where)
    if "id" not in raw or "name" not in raw or "kind" not in raw:
        raise InputError(f"{where}: 'id', 'name' and 'kind' are required")
    data = dict(raw)
    data["kind"] = _enum(EntityKind, data["kind"], where)
    if "gov_status" in data:
        data["gov_status"] = _enum(GovStatus, data["gov_status"], where)
    return Entity(**data)


def _holding(raw: dict[str, Any]) -> Holding:
    where = f"holding {raw.get('holder', '?')} -> {raw.get('held', '?')}"
    _check_keys(raw, Holding, where)
    if "holder" not in raw or "held" not in raw:
        raise InputError(f"{where}: 'holder' and 'held' are required")
    data = dict(raw)
    rights = []
    for r in data.get("future_rights", []):
        _check_keys(r, FutureRight, f"{where}, future right")
        r = dict(r)
        r["type"] = _enum(RightType, r["type"], where)
        r["mode"] = _enum(RightMode, r["mode"], where)
        rights.append(FutureRight(**r))
    data["future_rights"] = rights
    return Holding(**data)


def from_dict(data: dict[str, Any]) -> OwnershipGraph:
    """Build a graph from parsed YAML or JSON."""
    allowed = {"title", "buyer", "target", "entities", "holdings"}
    unknown = set(data) - allowed
    if unknown:
        raise InputError(f"top level: unknown field(s) {sorted(unknown)}")
    entities: dict[str, Entity] = {}
    for raw in data.get("entities", []):
        entity = _entity(raw)
        if entity.id in entities:
            raise InputError(f"entity id '{entity.id}' is used twice")
        entities[entity.id] = entity
    holdings = [_holding(raw) for raw in data.get("holdings", [])]
    return OwnershipGraph(
        title=data.get("title", "Untitled structure"),
        entities=entities,
        holdings=holdings,
        buyer=data.get("buyer"),
        target=data.get("target"),
    )


def load_yaml(path: str | Path) -> OwnershipGraph:
    """Read an ownership structure from a YAML file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise InputError(f"{path}: expected a mapping at the top level")
    return from_dict(data)
