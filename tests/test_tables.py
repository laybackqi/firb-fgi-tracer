"""Tests for the YAML writer and the table conversion used by the web app."""

from pathlib import Path

import pytest
import yaml

from firb_tracer.model import InputError, dump_yaml, from_dict, load_yaml
from firb_tracer.tables import from_rows, to_rows

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
NAN = float("nan")


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.yaml")), ids=lambda p: p.stem)
def test_yaml_round_trip(path):
    graph = load_yaml(path)
    assert from_dict(yaml.safe_load(dump_yaml(graph))) == graph


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.yaml")), ids=lambda p: p.stem)
def test_table_round_trip(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    entities, holdings, rights = to_rows(data)
    header = {k: data.get(k) for k in ("title", "buyer", "target", "transaction")}
    assert from_dict(from_rows(entities, holdings, rights, header)) == from_dict(data)


def test_empty_cells_and_blank_rows_are_ignored():
    entities = [
        {"id": "a", "name": "A", "kind": "government", "country": "CN", "gov_status": "FG",
         "acts_on_wishes_of": "", "fund_exemption_claimed": False, "note": NAN},
        {"id": "b", "name": "B", "kind": "corporation", "country": None, "gov_status": None},
        {"id": None, "name": "", "kind": None, "fund_exemption_claimed": False},  # left behind by the editor
    ]
    holdings = [{"holder": "a", "held": "b", "shares_pct": 30, "voting_pct": NAN, "veto": None,
                 "concert_with": " x, y ,", "source": "  "}]
    data = from_rows(entities, holdings, [], {"title": "T", "buyer": None})
    assert [e["id"] for e in data["entities"]] == ["a", "b"]
    assert "note" not in data["entities"][0] and "gov_status" not in data["entities"][1]
    assert data["holdings"][0] == {"holder": "a", "held": "b", "shares_pct": 30.0, "concert_with": ["x", "y"]}
    assert "buyer" not in data


def test_future_right_attaches_to_its_holding():
    holdings = [{"holder": "a", "held": "b", "shares_pct": 10}]
    rights = [{"holder": "a", "held": "b", "type": "call_option", "mode": "issue", "pct": 15}]
    data = from_rows([], holdings, rights, {})
    assert data["holdings"][0]["future_rights"] == [{"type": "call_option", "mode": "issue", "pct": 15.0}]


def test_future_right_without_a_holding_is_an_error():
    rights = [{"holder": "a", "held": "c", "type": "call_option", "mode": "issue", "pct": 15}]
    with pytest.raises(InputError, match="no holding from 'a' to 'c'"):
        from_rows([], [{"holder": "a", "held": "b"}], rights, {})


def test_non_numeric_percentage_is_an_error():
    with pytest.raises(InputError, match="shares_pct must be a number"):
        from_rows([], [{"holder": "a", "held": "b", "shares_pct": "ten"}], [], {})
