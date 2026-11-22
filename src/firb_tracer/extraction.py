"""What a text reader found, in a shape both readers share.

There are two readers of an ownership summary:

* text_rules.py reads fixed sentence patterns, with no outside service;
* llm_extract.py asks a language model the user connects with their own key.

Both return an Extraction. It is a draft for the user to check, never a
conclusion: Extraction.to_data() turns it into the input format, which the
app then puts into the three editable tables.

Two rules hold whichever reader is used:

* every entity's government status is "uncertain" (rule R1: characterising
  a government body is the user's call, never the reader's);
* every holding keeps the sentence it came from in its source field (R18),
  so the user can check each row against the original text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

GOVERNMENT_WORDS = re.compile(
    r"国资委|国有资产监督管理|人民政府|财政部|财政厅|财政局|国务院|"
    r"\bSASAC\b|\bGovernment\b|\bMinistry\b|\bState Council\b",
    re.I,
)
TRUST_OR_PARTNERSHIP_WORDS = re.compile(
    r"合伙|信托|基金|\bTrust\b|\bPartnership\b|\bL\.?P\.?\b|\bFund\b", re.I
)


@dataclass
class Found:
    """One holding read from the text."""

    holder: str
    held: str
    pct: float
    proposed: bool = False
    source: str = ""  # the sentence it was read from
    voting_pct: float | None = None
    veto: bool = False
    board_seats: str = ""


@dataclass
class Extraction:
    """A draft structure read from text, plus what the reader could not read."""

    holdings: list[Found] = field(default_factory=list)
    # Sentences about ownership or control that the reader could not turn into a holding.
    unread: list[str] = field(default_factory=list)
    buyer: str | None = None
    target: str | None = None
    kinds: dict[str, str] = field(default_factory=dict)  # name -> kind, where the reader knows
    countries: dict[str, str] = field(default_factory=dict)  # name -> ISO code, where stated
    notes: list[str] = field(default_factory=list)  # the reader's own warnings
    reader: str = ""  # "rules" or "model"

    # ------------------------------------------------------------------

    @property
    def names(self) -> list[str]:
        """Every entity, in the order it first appears."""
        seen: dict[str, None] = {}
        for h in self.holdings:
            seen.setdefault(h.holder)
            seen.setdefault(h.held)
        for extra in (self.buyer, self.target):
            if extra:
                seen.setdefault(extra)
        return list(seen)

    def kind_of(self, name: str) -> str:
        if name in self.kinds:
            return self.kinds[name]
        return "government" if GOVERNMENT_WORDS.search(name) else "corporation"

    def add(self, found: Found) -> None:
        """Add a holding; a later statement about the same holding replaces an earlier one.

        An existing holding and a proposed one between the same pair are kept
        apart: the engine adds the proposed row to the existing one to get the
        position after the transaction.
        """
        for i, h in enumerate(self.holdings):
            if h.holder == found.holder and h.held == found.held and h.proposed == found.proposed:
                if h.pct != found.pct:
                    self.notes.append(
                        f"{found.holder} → {found.held} appears twice ({h.pct:g}% and {found.pct:g}%); "
                        "kept the later one"
                    )
                self.holdings[i] = found
                return
        self.holdings.append(found)

    # ------------------------------------------------------------------

    def to_complete(self) -> list[str]:
        """What the user still has to fill in or check, in plain words."""
        todo = []
        if self.holdings:
            todo.append("Government status of every entity is set to uncertain: "
                        "mark each as FG, SGE or none, with a reason (R1).")
        if not any(h.proposed for h in self.holdings):
            todo.append("No proposed holding found: tick 'proposed' on the holding the transaction would create.")
        if self.buyer is None:
            todo.append("Buyer not identified: choose it in section 3.")
        if self.target is None:
            todo.append("Target not identified: choose the Australian target in section 3.")
        missing_country = [n for n in self.names if n not in self.countries]
        if missing_country:
            todo.append("Country is blank for " + ", ".join(missing_country) +
                        ": required for any entity you mark FG or SGE.")
        looks_like = [n for n in self.names if TRUST_OR_PARTNERSHIP_WORDS.search(n)]
        if looks_like:
            todo.append(", ".join(looks_like) + " may be a trust, fund or partnership: check its kind and "
                        "whether a trustee or general partner row is needed (R24).")
        todo.append("Kind is set to corporation unless the name looks like a government body: "
                    "correct individuals and other kinds in table 1.")
        todo.append("Check the transaction facts and exceptions in section 3.")
        return todo + self.notes

    def to_data(self, title: str = "Structure read from text") -> dict[str, Any]:
        """The input format that model.from_dict reads."""
        entities = []
        for name in self.names:
            entity: dict[str, Any] = {
                "id": name,
                "name": name,
                "kind": self.kind_of(name),
                "gov_status": "uncertain",
            }
            if name in self.countries:
                entity["country"] = self.countries[name]
            entities.append(entity)
        holdings = []
        for h in self.holdings:
            row: dict[str, Any] = {"holder": h.holder, "held": h.held, "shares_pct": h.pct}
            if h.voting_pct is not None:
                row["voting_pct"] = h.voting_pct
            if h.proposed:
                row["proposed"] = True
            if h.veto:
                row["veto"] = True
            if h.board_seats:
                row["board_seats"] = h.board_seats
            row["source"] = f"Text ({self.reader}): {h.source}" if h.source else f"Text ({self.reader})"
            holdings.append(row)
        data: dict[str, Any] = {"title": title, "entities": entities, "holdings": holdings}
        if self.buyer:
            data["buyer"] = self.buyer
            data["transaction"] = {"action": "acquire_interest"}
        if self.target:
            data["target"] = self.target
        return data
