"""Tests for the basic (fixed pattern) text reader."""

import pytest

from firb_tracer.model import from_dict
from firb_tracer.text_rules import read_text


def edges(x):
    return {(h.holder, h.held, h.pct, h.proposed) for h in x.holdings}


@pytest.mark.parametrize("text, expected", [
    ("甲公司持有乙公司25%股权", ("甲公司", "乙公司", 25.0)),
    ("甲公司持有乙公司 25.5% 的股份", ("甲公司", "乙公司", 25.5)),
    ("甲公司持有25%的乙公司股权", ("甲公司", "乙公司", 25.0)),
    ("乙公司由甲公司持股30%", ("甲公司", "乙公司", 30.0)),
    ("甲公司全资持有乙公司", ("甲公司", "乙公司", 100.0)),
    ("乙公司是甲公司的全资子公司", ("甲公司", "乙公司", 100.0)),
    ("Alpha Ltd holds 25% of Beta Pty Ltd", ("Alpha Ltd", "Beta Pty Ltd", 25.0)),
    ("Alpha Ltd owns a 25 per cent stake in Beta Pty Ltd", ("Alpha Ltd", "Beta Pty Ltd", 25.0)),
    ("Beta Pty Ltd is 40% owned by Alpha Ltd", ("Alpha Ltd", "Beta Pty Ltd", 40.0)),
    ("Beta Pty Ltd is a wholly owned subsidiary of Alpha Ltd", ("Alpha Ltd", "Beta Pty Ltd", 100.0)),
    ("Alpha Ltd holds 10% of Bank of China Limited", ("Alpha Ltd", "Bank of China Limited", 10.0)),
    ("Alpha Co., Ltd. holds 10% of Beta Ltd", ("Alpha Co. Ltd", "Beta Ltd", 10.0)),
])
def test_sentence_forms(text, expected):
    x = read_text(text)
    assert edges(x) == {(*expected, False)}
    assert x.unread == []


@pytest.mark.parametrize("text", [
    "甲公司拟收购乙公司15%股权",
    "甲公司拟收购乙公司另外15%股权",
    "Alpha Ltd proposes to acquire a further 15% of Beta Ltd",
    "Alpha Ltd will acquire 15% of Beta Ltd",
])
def test_proposed_acquisitions(text):
    x = read_text(text)
    assert len(x.holdings) == 1 and x.holdings[0].proposed and x.holdings[0].pct == 15.0
    assert x.buyer == x.holdings[0].holder


def test_shareholder_list_with_heading():
    x = read_text("乙公司股东如下：\n- 甲公司 60%\n- 25% 丙公司\n3. 丁合伙企业（有限合伙）：15%")
    assert edges(x) == {("甲公司", "乙公司", 60.0, False), ("丙公司", "乙公司", 25.0, False),
                        ("丁合伙企业(有限合伙)", "乙公司", 15.0, False)}


def test_shareholder_list_on_one_line_and_in_english():
    x = read_text("乙公司的股东：甲公司 60%，丙公司 40%\nShareholders of Gamma Ltd: Alpha Ltd 30%; Beta Ltd 70%")
    assert len(x.holdings) == 4


def test_a_sentence_after_a_list_ends_the_list():
    x = read_text("乙公司股东：\n甲公司 60%\n丙公司由丁公司持股30%")
    assert ("丁公司", "丙公司", 30.0, False) in edges(x)


def test_percentage_without_holder_is_unread_outside_a_list():
    x = read_text("25% C公司")
    assert x.holdings == [] and x.unread == ["25% C公司"]


def test_indirect_percentages_are_never_read_as_holdings():
    x = read_text("甲公司通过乙公司间接持有丙公司10%。Alpha Ltd indirectly holds 5% of Gamma Ltd.")
    assert x.holdings == [] and len(x.unread) == 2


def test_defined_terms_and_roles():
    text = ('深圳市国资委持有深圳市资源集团有限公司（以下简称"深圳资源"）100%股权。\n'
            "深圳资源拟收购香港控股有限公司25%股权。\n目标公司为澳洲稀土有限公司。")
    x = read_text(text)
    assert ("深圳市资源集团有限公司", "香港控股有限公司", 25.0, True) in edges(x)
    assert x.buyer == "深圳市资源集团有限公司" and x.target == "澳洲稀土有限公司"


def test_english_defined_buyer_and_relative_clause():
    text = ('Shenzhen SASAC owns 100% of Shenzhen Resources Group Co., Ltd. (the "Buyer"). '
            "The Buyer holds 25% of HK HoldCo Limited, which holds 12% of Australian Rare Earths Ltd. "
            "Target: Australian Rare Earths Ltd")
    x = read_text(text)
    assert x.buyer == "Shenzhen Resources Group Co. Ltd"
    assert ("HK HoldCo Limited", "Australian Rare Earths Ltd", 12.0, False) in edges(x)
    assert x.target == "Australian Rare Earths Ltd"


def test_existing_and_proposed_between_the_same_pair_are_both_kept():
    x = read_text("甲公司持有乙公司25%股权。甲公司拟收购乙公司另外15%股权。")
    assert edges(x) == {("甲公司", "乙公司", 25.0, False), ("甲公司", "乙公司", 15.0, True)}


def test_control_statements_are_listed_as_unread():
    x = read_text("甲公司持有乙公司25%股权。甲公司有权委派乙公司2名董事。The Buyer has a veto over budgets.")
    assert x.unread == ["甲公司有权委派乙公司2名董事", "The Buyer has a veto over budgets."]


def test_draft_goes_through_the_engine():
    x = read_text("国资委持有甲公司100%股权。甲公司拟收购乙公司25%股权。")
    graph = from_dict(x.to_data())
    assert not [i for i in graph.validate() if i.level == "error"]
    assert all(e.gov_status.value == "uncertain" for e in graph.entities.values())
    assert graph.entities["国资委"].kind.value == "government"
    assert graph.buyer == "甲公司"
    assert all(h.source.startswith("Text (rules): ") for h in graph.holdings)
    assert any("uncertain" in t for t in x.to_complete())


@pytest.mark.parametrize("text", ["深圳资源拟从李四处受让香港控股有限公司15%股权",
                                  "Alpha Ltd proposes to acquire 15% of HK HoldCo Limited from Li Si"])
def test_seller_is_not_part_of_the_name(text):
    (h,) = read_text(text).holdings
    assert h.held in ("香港控股有限公司", "HK HoldCo Limited") and h.proposed and h.pct == 15.0
