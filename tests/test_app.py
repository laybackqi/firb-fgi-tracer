"""Runs the Streamlit app headless. Skipped if Streamlit is not installed."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_app_opens_on_the_offshore_example():
    at = run()
    assert any("Notifiable." in e.value for e in at.error)
    assert any("FATR s 17(1)(b)(i)" in m.value for m in at.markdown)
    assert [t.label for t in at.tabs][-2:] == ["Report", "Structure diagram"]


def test_unticking_mining_flag_changes_triggers():
    at = run()
    at.checkbox(key="target_is_mining_entity_1").uncheck().run()
    assert not at.exception
    banner = next(e.value for e in at.error if "Notifiable." in e.value)
    assert "56(1)(a)" in banner and "56(1)(c)(ii)" not in banner


def test_loading_another_example():
    at = run()
    at.sidebar.selectbox[0].select("t04_same_country").run()
    at.sidebar.button[0].click().run()
    assert not at.exception
    assert any("No buyer selected" in i.value for i in at.info)
    assert any("D Co is a foreign government investor" in m.value for m in at.markdown)


def test_blank_start_prompts_for_entities():
    at = run()
    at.sidebar.button[1].click().run()
    assert not at.exception
    assert any("Add the entities" in i.value for i in at.info)


def test_parties_show_full_names_and_flags_have_tooltips():
    at = run()
    buyer = at.selectbox(key="buyer_1")
    assert buyer.value == "City-SZ_SOE"
    assert "Shenzhen Resources Group (hypothetical) (City-SZ_SOE)" in buyer.options
    mining = at.checkbox(key="target_is_mining_entity_1")
    assert mining.label == "Mining target" and "56(1)(c)(ii)" in mining.help


def test_typo_in_holder_id_is_flagged_next_to_the_table():
    at = run()
    at.session_state["holdings_1"] = {"edited_rows": {0: {"holder": "City-SZ_SASC"}},
                                      "added_rows": [], "deleted_rows": []}
    at.run()
    assert not at.exception
    assert any("`City-SZ_SASC` is not an entity id" in w.value for w in at.warning)



def _click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception


def test_text_summary_basic_reader_draft_then_apply():
    at = run()
    _click(at, "中文")
    assert "深圳市国资委" in at.text_area(key="source_text").value
    _click(at, "Read with the basic reader")
    assert any("Draft from the basic reader: 5 holdings among 5 entities" in m.value for m in at.markdown)
    assert any("委派" in w.value for w in at.warning)  # the director sentence is listed as unread
    assert at.selectbox(key="buyer_1").value == "City-SZ_SOE"  # tables unchanged until applied
    _click(at, "Replace the tables with this draft")
    assert at.selectbox(key="buyer_2").value == "深圳市资源集团有限公司"
    assert at.selectbox(key="target_2").value == "澳洲稀土有限公司"
    assert "text summary" in at.sidebar.caption[0].value
    # an unchecked draft never shows a green all-clear
    assert not at.success
    assert any("Provisional." in w.value for w in at.warning)
    assert any("(provisional)" in m.value for m in at.metric)


def test_discard_keeps_the_tables():
    at = run()
    _click(at, "English")
    _click(at, "Read with the basic reader")
    _click(at, "Discard")
    assert not any("Draft from" in m.value for m in at.markdown)
    assert at.selectbox(key="buyer_1").value == "City-SZ_SOE"


def test_model_reader_without_key_explains():
    at = run()
    _click(at, "English")
    _click(at, "Read with the model")
    assert any("all needed" in e.value for e in at.error)


def test_draft_then_characterise_government_gives_a_result():
    at = run()
    _click(at, "中文")
    _click(at, "Read with the basic reader")
    _click(at, "Replace the tables with this draft")
    # the user marks the SASAC as a foreign government and the rest as none
    edits = {0: {"gov_status": "FG", "country": "CN", "gov_reason": "Shenzhen municipal SASAC"}}
    edits.update({i: {"gov_status": "none"} for i in range(1, 5)})
    at.session_state["entities_2"] = {"edited_rows": edits, "added_rows": [], "deleted_rows": []}
    at.run()
    assert not at.exception
    assert any("Notifiable." in e.value for e in at.error)
    assert not any("Provisional." in w.value for w in at.warning)
    # 10% of HK HoldCo is below 20%, so nothing traces to the target before; 25% after carries its 12% (s 19)
    assert [m.value for m in at.metric][:3] == ["Yes", "0%", "12%"]
