"""Tests for the data model: loading and input validation."""

from pathlib import Path

import pytest

from firb_tracer.model import (
    EntityKind,
    GovStatus,
    InputError,
    from_dict,
    load_yaml,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def errors(graph):
    return [i for i in graph.validate() if i.level == "error"]


def warnings(graph):
    return [i for i in graph.validate() if i.level == "warning"]


def test_t04_loads_and_is_valid():
    graph = load_yaml(EXAMPLES / "t04_same_country.yaml")
    assert len(graph.entities) == 3
    assert len(graph.holdings) == 2
    sz = graph.entities["City-SZ_SASAC"]
    assert sz.kind is EntityKind.GOVERNMENT
    assert sz.gov_status is GovStatus.FG
    assert sz.is_government
    assert not graph.entities["Company-D"].is_government
    assert [h.holder for h in graph.holders_of("Company-D")] == ["City-SZ_SASAC", "City-GZ_SASAC"]
    assert errors(graph) == []


def test_typo_in_field_name_is_rejected():
    data = {
        "entities": [{"id": "a", "name": "A", "kind": "corporation"}],
        "holdings": [{"holder": "a", "held": "a", "share_pct": 10}],  # typo
    }
    with pytest.raises(InputError, match="share_pct"):
        from_dict(data)


def test_unknown_gov_status_is_rejected():
    data = {"entities": [{"id": "a", "name": "A", "kind": "corporation", "gov_status": "SOE"}]}
    with pytest.raises(InputError, match="SOE"):
        from_dict(data)


def test_government_needs_a_country():
    data = {"entities": [{"id": "a", "name": "A", "kind": "government", "gov_status": "FG", "gov_reason": "x"}]}
    assert any("country" in i.message for i in errors(from_dict(data)))


def test_shares_over_100_percent_is_an_error():
    data = {
        "entities": [
            {"id": "a", "name": "A", "kind": "corporation"},
            {"id": "b", "name": "B", "kind": "corporation"},
            {"id": "t", "name": "T", "kind": "corporation"},
        ],
        "holdings": [
            {"holder": "a", "held": "t", "shares_pct": 60, "source": "s"},
            {"holder": "b", "held": "t", "shares_pct": 50, "source": "s"},
        ],
    }
    assert any("110%" in i.message for i in errors(from_dict(data)))


def test_trustee_must_name_its_trust():
    data = {"entities": [{"id": "tr", "name": "XX Trust Co", "kind": "trustee"}]}
    assert any("R24" in i.message for i in errors(from_dict(data)))


def test_control_signals_without_controller_prompt_review():
    data = {
        "entities": [
            {"id": "x", "name": "X", "kind": "corporation", "control_indicators": ["cadre_appointment"]}
        ]
    }
    assert any("s 6(1)(f)" in i.message for i in warnings(from_dict(data)))


def test_veto_and_missing_source_are_flagged():
    data = {
        "entities": [
            {"id": "a", "name": "A", "kind": "corporation"},
            {"id": "t", "name": "T", "kind": "corporation"},
        ],
        "holdings": [{"holder": "a", "held": "t", "shares_pct": 5, "veto": True}],
    }
    messages = " ".join(i.message for i in warnings(from_dict(data)))
    assert "s 22(4)" in messages
    assert "R18" in messages


def _two_holders(proposed_pct, existing_other=75.0):
    from firb_tracer.model import from_dict
    return from_dict({
        "title": "t",
        "entities": [{"id": i, "name": i, "kind": "corporation"} for i in ("a", "b", "c")],
        "holdings": [
            {"holder": "a", "held": "c", "shares_pct": 25, "source": "s"},
            {"holder": "b", "held": "c", "shares_pct": existing_other, "source": "s"},
            {"holder": "a", "held": "c", "shares_pct": proposed_pct, "proposed": True, "source": "s"},
        ],
    })


def test_buying_from_an_existing_holder_is_a_warning_not_an_error():
    issues = _two_holders(15).validate()
    assert not [i for i in issues if i.level == "error"]
    assert any("reduction is not modelled" in i.message for i in issues if i.level == "warning")


def test_existing_holdings_over_100_are_still_an_error():
    issues = _two_holders(15, existing_other=80).validate()
    assert any("more than 100%" in i.message for i in issues if i.level == "error")
