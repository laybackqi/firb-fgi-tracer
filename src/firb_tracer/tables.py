"""Flat tables for the web app, and back.

The web app edits the structure as three spreadsheet-style tables:
entities, holdings and future rights. This module turns the input format
(the dict that model.from_dict reads) into rows, and rows back into that
dict. It has no Streamlit or pandas dependency, so it can be tested alone.

Conventions for the rows:

* a list field (acts_on_wishes_of, control_indicators, concert_with) is a
  comma-separated string;
* an empty cell (None, NaN or "") means "not given", and the field takes its
  default;
* a row with every cell empty is ignored, because the table editor leaves
  blank rows behind;
* each future right names the holding it belongs to by holder and held.
"""

from __future__ import annotations

import math
from typing import Any

from .model import InputError

ENTITY_COLUMNS = [
    "id", "name", "kind", "country", "gov_status", "gov_reason",
    "capacity_of", "acts_on_wishes_of", "control_indicators",
    "fund_exemption_claimed", "note",
]
HOLDING_COLUMNS = [
    "holder", "held", "shares_pct", "voting_pct", "distribution_pct",
    "max_distribution_pct", "proposed", "veto", "veto_scope", "board_seats",
    "management_influence", "concert_with", "source",
]
RIGHT_COLUMNS = ["holder", "held", "type", "mode", "pct", "counterparty", "note"]

LIST_FIELDS = {"acts_on_wishes_of", "control_indicators", "concert_with"}
BOOL_FIELDS = {"fund_exemption_claimed", "proposed", "veto", "management_influence"}
NUMBER_FIELDS = {"shares_pct", "voting_pct", "distribution_pct", "max_distribution_pct", "pct"}


# --------------------------------------------------------------------------
# Input format -> rows
# --------------------------------------------------------------------------


def _cell(name: str, value: Any) -> Any:
    if name in LIST_FIELDS:
        return ", ".join(value or [])
    if name in BOOL_FIELDS:
        return bool(value)
    return value


def to_rows(data: dict[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split the input format into entity, holding and future-right rows."""
    entities = [{c: _cell(c, raw.get(c)) for c in ENTITY_COLUMNS} for raw in data.get("entities", [])]
    holdings, rights = [], []
    for raw in data.get("holdings", []):
        holdings.append({c: _cell(c, raw.get(c)) for c in HOLDING_COLUMNS})
        for r in raw.get("future_rights", []):
            row = {c: r.get(c) for c in RIGHT_COLUMNS}
            row["holder"], row["held"] = raw.get("holder"), raw.get("held")
            rights.append(row)
    return entities, holdings, rights


# --------------------------------------------------------------------------
# Rows -> input format
# --------------------------------------------------------------------------


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def _clean(row: dict[str, Any], where: str) -> dict[str, Any]:
    """Drop empty cells and convert the rest to the input format's types."""
    out: dict[str, Any] = {}
    for name, value in row.items():
        if name in BOOL_FIELDS:
            if not _empty(value) and bool(value):
                out[name] = True
            continue
        if _empty(value):
            continue
        if name in LIST_FIELDS:
            items = [v.strip() for v in str(value).split(",") if v.strip()]
            if items:
                out[name] = items
        elif name in NUMBER_FIELDS:
            try:
                out[name] = float(value)
            except (TypeError, ValueError):
                raise InputError(f"{where}: {name} must be a number, got '{value}'") from None
        else:
            out[name] = str(value).strip()
    return out


def _real(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Leave out rows where the user filled in nothing (booleans don't count)."""
    return [r for r in rows if any(not _empty(v) and not isinstance(v, bool) for v in r.values())]


def from_rows(
    entities: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    rights: list[dict[str, Any]],
    header: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild the input format from the three tables plus title, parties and transaction."""
    data: dict[str, Any] = {k: v for k, v in header.items() if v is not None}

    data["entities"] = []
    for i, row in enumerate(_real(entities), start=1):
        data["entities"].append(_clean(row, f"entities row {i}"))

    data["holdings"] = []
    for i, row in enumerate(_real(holdings), start=1):
        data["holdings"].append(_clean(row, f"holdings row {i}"))

    for i, row in enumerate(_real(rights), start=1):
        right = _clean(row, f"future rights row {i}")
        holder, held = right.pop("holder", None), right.pop("held", None)
        match = next((h for h in data["holdings"] if h.get("holder") == holder and h.get("held") == held), None)
        if match is None:
            raise InputError(
                f"future rights row {i}: there is no holding from '{holder}' to '{held}' to attach it to"
            )
        match.setdefault("future_rights", []).append(right)

    return data
