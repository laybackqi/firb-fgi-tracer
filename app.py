"""Web interface for the FIRB foreign government investor screener.

Run locally:      streamlit run app.py
Deploy:           Streamlit Community Cloud, main file app.py

The app is a thin layer over the engine in src/firb_tracer: it collects the
structure in three tables, rebuilds the same input the command line reads
(model.from_dict), and shows the same Markdown report. Section 0 can draft
those tables from a text summary (text_rules.py, or llm_extract.py with the
user's own API key); the draft only replaces the tables when the user says so.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))  # so the app runs without `pip install -e .`

from firb_tracer.diagram import to_dot  # noqa: E402
from firb_tracer.documents import DocumentError, extract_text  # noqa: E402
from firb_tracer.extraction import Extraction  # noqa: E402
from firb_tracer.fgi import determine_fgi  # noqa: E402
from firb_tracer.llm_extract import PROVIDERS, ModelError, read_with_model  # noqa: E402
from firb_tracer.model import (  # noqa: E402
    Action, EntityKind, GovStatus, InputError, RightMode, RightType, Transaction, from_dict,
)
from firb_tracer.notification import assess  # noqa: E402
from firb_tracer.report import (  # noqa: E402
    DISCLAIMER, LEGISLATION, provisional_note, render_markdown, uncertain_entities,
)
from firb_tracer.text_rules import read_text  # noqa: E402
from firb_tracer.tables import (  # noqa: E402
    BOOL_FIELDS, ENTITY_COLUMNS, HOLDING_COLUMNS, NUMBER_FIELDS, RIGHT_COLUMNS, from_rows, to_rows,
)

EXAMPLES = ROOT / "examples"
REPO_URL = "https://github.com/laybackqi/firb-fgi-tracer"
NONE = "(none)"

HOLDER_HELP = "Type the id of the owner, copied from the id column of table 1 (e.g. City-SZ_SOE)."
HELD_HELP = "Type the id of the company owned, copied from the id column of table 1 (e.g. HK_HoldCo)."

# Transaction flags: (short label, tooltip). The tooltip shows on the (?) icon.
FACT_FLAGS = {
    "target_is_australian": (
        "Australian target",
        "The target is an Australian entity or an Australian business. "
        "Needed for FATR s 56(1)(a): acquiring a direct interest in an Australian entity or business."),
    "target_is_mining_entity": (
        "Mining target",
        "The target is a mining, production or exploration entity. "
        "Acquiring 10% or more of one is notifiable under FATR s 56(1)(c)(ii)."),
    "business_arrangement": (
        "Business arrangement",
        "The buyer has a legal arrangement relating to the target's business. "
        "With one, 5% is enough for a direct interest (FATR s 16(b)); without it, 10% (s 16(a))."),
}
EXCEPTION_FLAGS = {
    "new_wholly_owned_subsidiary": (
        "New wholly owned subsidiary",
        "The interest is acquired by setting up a new wholly owned subsidiary. FATR s 56(3)."),
    "offshore_non_material": (
        "Offshore, non-material",
        "A non-material interest acquired through a foreign entity. Tick only after confirming every "
        "condition in FATR s 56(4)(a)-(d)."),
    "consortium_initial_interest": (
        "Consortium initial interest",
        "An initial interest in an entity set up by a consortium for a later notifiable acquisition. "
        "FATR s 56(5)."),
    "passive_increase": (
        "Passive increase",
        "The percentage rises without the buyer acquiring new securities, e.g. through a buy-back "
        "(FATA s 18A). Excepted only if the buyer already held a direct interest (s 56(6)) or, for "
        "a mining target, 10% (s 56(7))."),
}

st.set_page_config(page_title="FIRB FGI Screener", page_icon="⚖️", layout="wide")


# --------------------------------------------------------------------------
# State: the current input, and a version number for the editor widgets.
# Loading new input bumps the version, which gives every widget a fresh key.
# --------------------------------------------------------------------------


def example_files() -> dict[str, Path]:
    return {p.stem: p for p in sorted(EXAMPLES.glob("*.yaml"))}


def load(data: dict, label: str) -> None:
    from_dict(data)  # fail early on a malformed file, before replacing anything
    st.session_state.doc = data
    st.session_state.ver = st.session_state.get("ver", 0) + 1
    st.session_state.loaded = label


if "doc" not in st.session_state:
    first = example_files().get("hk_holdco_miner")
    load(yaml.safe_load(first.read_text(encoding="utf-8")) if first else {"title": "New structure"},
         "hk holdco miner (example)" if first else "blank")

doc: dict = st.session_state.doc
v: int = st.session_state.ver


# --------------------------------------------------------------------------
# Sidebar: load and save input
# --------------------------------------------------------------------------

with st.sidebar:
    st.header("Input")
    examples = example_files()
    choice = st.selectbox("Example structures", list(examples), format_func=lambda s: s.replace("_", " "))
    if st.button("Load example", width="stretch"):
        load(yaml.safe_load(examples[choice].read_text(encoding="utf-8")), choice.replace("_", " ") + " (example)")
        st.rerun()

    if st.button("Start blank", width="stretch"):
        load({"title": "New structure", "entities": [], "holdings": []}, "blank")
        st.rerun()

    st.caption(f"Loaded: {st.session_state.loaded}")
    st.divider()
    st.markdown(
        "**What this does.** Traces a buyer's ownership chain and applies the foreign government "
        "investor test (FATR s 17) and the notification test for foreign government investors "
        "(FATR s 56). Characterising each government body is your call (rule R1)."
    )
    st.caption(f"Law as at: {LEGISLATION}")
    st.caption(DISCLAIMER)
    st.caption(f"[Source code]({REPO_URL})")


# --------------------------------------------------------------------------
# Main: the three tables and the transaction
# --------------------------------------------------------------------------

st.title("FIRB foreign government investor screener")
st.caption("Enter the ownership structure, mark the government bodies, and the report updates as you type.")


# --------------------------------------------------------------------------
# 0 · Start from a text summary: read it into a draft, then replace the tables
# --------------------------------------------------------------------------

EXAMPLE_TEXTS = {
    "en": (
        'Shenzhen SASAC owns 100% of Shenzhen Resources Group Co., Ltd. (the "Buyer").\n'
        "Shareholders of HK HoldCo Limited:\n"
        "- Shenzhen Resources Group Co., Ltd. 10%\n"
        "- Li Si 90%\n\n"
        "HK HoldCo Limited holds 12% of Australian Rare Earths Ltd.\n"
        "The Buyer proposes to acquire a further 15% of HK HoldCo Limited from Li Si.\n"
        "Target: Australian Rare Earths Ltd.\n"
        "The Buyer may nominate one of the three directors of HK HoldCo Limited."
    ),
    "zh": (
        "深圳市国资委持有深圳市资源集团有限公司（以下简称“深圳资源”）100%股权。\n"
        "香港控股有限公司股东如下：\n"
        "深圳资源 10%\n"
        "李四 90%\n\n"
        "香港控股有限公司持有澳洲稀土有限公司12%股权。\n"
        "深圳资源拟从李四处受让香港控股有限公司15%股权。\n"
        "目标公司为澳洲稀土有限公司。\n"
        "深圳资源有权委派香港控股有限公司三名董事中的一名。"
    ),
}

BASIC_GUIDE = """
The basic reader understands **one statement per sentence or line**, in Chinese or English:

| Form | Examples |
|---|---|
| Holding | `A 持有 B 25% 股权` · `A holds 25% of B` · `B is 25% owned by A` · `B 由 A 持股 25%` |
| Wholly owned | `A 全资持有 B` · `B 是 A 的全资子公司` · `B is a wholly owned subsidiary of A` |
| Proposed | `A 拟收购 B 15% 股权` · `A proposes to acquire 15% of B` (marked *proposed*) |
| Shareholder list | a heading naming the company, then one shareholder per line or separated by commas: `B 的股东：A 25%，C 75%` · `Shareholders of B:` then `A 25%` |
| Short names | `深圳资源集团有限公司（以下简称"深圳资源"）` · `Alpha Pty Ltd (the "Buyer")` |
| Parties | `Buyer: A` · `目标公司为 B` |

**Not read** (listed afterwards so you can enter them by hand or use the advanced reader):
a percentage with no holder, such as `25% C公司` on its own (it works under a shareholder-list heading);
indirect or look-through percentages (`A 通过 B 间接持有 C 10%`); veto rights, board seats,
voting agreements and other control arrangements. In Word tables, each row is read as one list line.
"""

PRIVACY_NOTE = (
    "Your text and key go **directly from this app to the service you choose**, and the service's own "
    "terms apply. The key stays only in this browser session and is never saved. For confidential "
    "client matters, remove names first, or run the tool on your own computer. "
    "The basic reader sends nothing anywhere."
)


def _upload_changed() -> None:
    upload = st.session_state.get("source_upload")
    if upload is None:
        return
    try:
        st.session_state.source_text = extract_text(upload.name, upload.getvalue())
        st.session_state.upload_error = None
    except DocumentError as exc:
        st.session_state.upload_error = str(exc)


def _use_example(lang: str) -> None:
    st.session_state.source_text = EXAMPLE_TEXTS[lang]
    st.session_state.draft = None


def _apply_draft() -> None:
    draft: Extraction = st.session_state.draft
    load(draft.to_data(), f"text summary ({draft.reader} reader)")
    st.session_state.draft = None


def _discard_draft() -> None:
    st.session_state.draft = None


st.subheader("0 · Start from a text summary")
st.caption("Optional. Paste the ownership part of a memo or upload a file, and the tool drafts the tables "
           "below for you to check. Or skip this and fill in the tables directly.")

up_col, ex_col = st.columns([3, 2])
with up_col:
    st.file_uploader("Upload Word, PDF or text", type=["docx", "pdf", "txt", "md"], key="source_upload",
                     on_change=_upload_changed,
                     help="The text is taken out of the file here; nothing is sent anywhere. "
                          "Scanned PDFs have no text and cannot be read.")
    if st.session_state.get("upload_error"):
        st.error(f"Could not use that file: {st.session_state.upload_error}")
with ex_col:
    st.caption("Or try an example text")
    e1, e2 = st.columns(2)
    e1.button("English", on_click=_use_example, args=("en",), width="stretch")
    e2.button("中文", on_click=_use_example, args=("zh",), width="stretch")

st.text_area("Ownership summary", key="source_text", height=180,
             placeholder="e.g. 甲公司持有乙公司25%股权。\nAlpha Ltd proposes to acquire 15% of Beta Pty Ltd.")

basic_tab, advanced_tab = st.tabs(["Basic reader · no key", "Advanced reader · your own API key"])
with basic_tab:
    st.caption("Reads fixed sentence patterns and keywords. Works offline; nothing is sent anywhere.")
    with st.expander("What the basic reader can and cannot read"):
        st.markdown(BASIC_GUIDE)
    if st.button("Read with the basic reader", type="primary"):
        st.session_state.draft = read_text(st.session_state.get("source_text", ""))

with advanced_tab:
    st.caption("For long or loosely written text and more complex structures. Uses a language model "
               "through your own API key; any OpenAI-compatible service works.")
    st.info(PRIVACY_NOTE, icon="🔒")
    provider = st.selectbox("Service", list(PROVIDERS), key="llm_provider")
    preset = PROVIDERS[provider]
    a1, a2 = st.columns(2)
    base_url = a1.text_input("Base URL", preset["base_url"], key=f"llm_url_{provider}",
                             help="The service's OpenAI-compatible address, ending before /chat/completions.")
    model_name = a2.text_input("Model", preset["model"], key=f"llm_model_{provider}",
                               placeholder="model name from your provider",
                               help="Model names change; check your provider's current list.")
    api_key = st.text_input("API key", type="password", key="llm_key", help="Kept in this session only.")
    if st.button("Read with the model", type="primary"):
        with st.spinner("Waiting for the model…"):
            try:
                st.session_state.draft = read_with_model(
                    st.session_state.get("source_text", ""), base_url, api_key, model_name)
            except ModelError as exc:
                st.error(f"The model could not read the text: {exc}")

draft: Extraction | None = st.session_state.get("draft")
if draft is not None:
    with st.container(border=True):
        who = "basic reader" if draft.reader == "rules" else "model"
        if draft.holdings:
            st.markdown(f"**Draft from the {who}: {len(draft.holdings)} holdings among "
                        f"{len(draft.names)} entities.** Nothing has changed yet.")
            st.dataframe(
                pd.DataFrame([{"holder": h.holder, "held": h.held, "%": h.pct, "proposed": h.proposed,
                               "from the text": h.source} for h in draft.holdings]),
                hide_index=True, width="stretch")
            st.caption(f"Buyer: {draft.buyer or 'not found'} · Target: {draft.target or 'not found'}")
        else:
            st.warning(f"The {who} found no holdings in this text.")
        if draft.unread:
            st.warning("**Not read — enter these by hand after applying:**\n\n"
                       + "\n".join(f"- {s}" for s in draft.unread), icon="✏️")
        if draft.holdings:
            st.info("**After applying, still to do:**\n\n" + "\n".join(f"- {t}" for t in draft.to_complete()))
            b1, b2 = st.columns(2)
            b1.button("Replace the tables with this draft", type="primary", on_click=_apply_draft, width="stretch")
            b2.button("Discard", on_click=_discard_draft, width="stretch")
        else:
            st.button("Discard", on_click=_discard_draft)

st.divider()

entity_rows, holding_rows, right_rows = to_rows(doc)


def _frame(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    """Rows as a table; empty text cells show blank rather than 'None'."""
    df = pd.DataFrame(rows, columns=columns)
    for c in columns:
        if c in NUMBER_FIELDS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        elif c not in BOOL_FIELDS:
            df[c] = df[c].where(df[c].notna(), "").astype(str)
    return df


title = st.text_input("Structure title", doc.get("title", ""), key=f"title_{v}")

st.subheader("1 · Entities")
st.caption("One row per person in the structure. A trustee or general partner gets one row per trust "
           "or partnership it acts for (R24).")
entities_df = st.data_editor(
    _frame(entity_rows, ENTITY_COLUMNS),
    key=f"entities_{v}",
    num_rows="dynamic",
    width="stretch",
    hide_index=True,
    column_config={
        "id": st.column_config.TextColumn("id", help="Short unique code, used in the holdings table", required=True),
        "name": st.column_config.TextColumn("name", required=True),
        "kind": st.column_config.SelectboxColumn("kind", options=[k.value for k in EntityKind], required=True),
        "country": st.column_config.TextColumn("country", help="ISO code, e.g. CN. Required for FG and SGE."),
        "gov_status": st.column_config.SelectboxColumn(
            "gov_status", options=[g.value for g in GovStatus], default=GovStatus.NONE.value,
            help="Your characterisation under FATA s 4: FG, SGE, none, or uncertain"),
        "gov_reason": st.column_config.TextColumn("gov_reason", help="Why you characterised it this way", width="large"),
        "capacity_of": st.column_config.TextColumn("capacity_of", help="Trustees and GPs: which trust or ULP"),
        "acts_on_wishes_of": st.column_config.TextColumn(
            "acts_on_wishes_of", help="FATA s 6(1)(f): ids whose wishes senior officers act on, comma-separated"),
        "control_indicators": st.column_config.TextColumn(
            "control_indicators", help="Non-equity control evidence, comma-separated (R8)"),
        "fund_exemption_claimed": st.column_config.CheckboxColumn(
            "fund exemption", help="FATR s 17(2): collective investment scheme exception claimed"),
        "note": st.column_config.TextColumn("note"),
    },
)

ids = [str(i).strip() for i in entities_df["id"].tolist() if isinstance(i, str) and i.strip()]

st.subheader("2 · Holdings")
st.caption("One row per holding: the owner goes in **holder**, the company it owns in **held**. "
           "Type the ids exactly as they appear in table 1. Tick **proposed** for the holding the "
           "transaction would create.")
st.caption(f"Entity ids to use: {', '.join(f'`{i}`' for i in ids) or 'none yet — add entities first'}")
holdings_df = st.data_editor(
    _frame(holding_rows, HOLDING_COLUMNS),
    key=f"holdings_{v}",
    num_rows="dynamic",
    width="stretch",
    hide_index=True,
    column_config={
        "holder": st.column_config.TextColumn("holder ✎", required=True, help=HOLDER_HELP),
        "held": st.column_config.TextColumn("held ✎", required=True, help=HELD_HELP),
        "shares_pct": st.column_config.NumberColumn("shares %", min_value=0.0, max_value=100.0,
                                                    help="Issued securities, FATA s 17(1)(b)"),
        "voting_pct": st.column_config.NumberColumn("voting %", min_value=0.0, max_value=100.0,
                                                    help="Only if different from shares, s 17(1)(a)"),
        "distribution_pct": st.column_config.NumberColumn("distribution %", min_value=0.0, max_value=100.0,
                                                          help="Trusts and ULPs, s 11A, s 17(2A)"),
        "max_distribution_pct": st.column_config.NumberColumn("max distribution %", min_value=0.0, max_value=100.0,
                                                              help="Discretionary trusts, s 18(3)"),
        "proposed": st.column_config.CheckboxColumn("proposed"),
        "veto": st.column_config.CheckboxColumn("veto", help="s 22(4): counted as 20% potential voting power (R15)"),
        "veto_scope": st.column_config.TextColumn("veto scope"),
        "board_seats": st.column_config.TextColumn("board seats", help="e.g. 1/5"),
        "management_influence": st.column_config.CheckboxColumn("mgmt influence", help="FATR s 16(c), target only"),
        "concert_with": st.column_config.TextColumn("concert with", help="FATA s 6(1)(b): ids, comma-separated"),
        "source": st.column_config.TextColumn("source", help="Where the figures come from (R18)", width="large"),
    },
)



def unknown_ids(df: pd.DataFrame, table: str) -> list[str]:
    """Ids typed in holder/held that are not in table 1, as readable notes."""
    notes = []
    for n, row in enumerate(df.to_dict("records"), start=1):
        for col in ("holder", "held"):
            value = row.get(col)
            if isinstance(value, str) and value.strip() and value.strip() not in ids:
                notes.append(f"{table} row {n}, {col}: `{value.strip()}` is not an entity id")
    return notes


holding_notes = unknown_ids(holdings_df, "Holdings")
if holding_notes:
    st.warning("Check the ids — " + "; ".join(holding_notes) + ".", icon="✏️")

with st.expander(f"Future rights — options, convertibles, subscriptions ({len(right_rows)})"):
    st.caption("Each right attaches to the holding with the same holder and held. "
               "**transfer**: existing securities change hands; **issue**: new securities are issued (R20).")
    rights_df = st.data_editor(
        _frame(right_rows, RIGHT_COLUMNS),
        key=f"rights_{v}",
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "holder": st.column_config.TextColumn("holder ✎", required=True, help=HOLDER_HELP),
            "held": st.column_config.TextColumn("held ✎", required=True, help=HELD_HELP),
            "type": st.column_config.SelectboxColumn("type", options=[r.value for r in RightType], required=True),
            "mode": st.column_config.SelectboxColumn("mode", options=[m.value for m in RightMode], required=True),
            "pct": st.column_config.NumberColumn("pct", min_value=0.0, max_value=100.0,
                                                 help="% of issued securities before exercise"),
        },
    )
    right_notes = unknown_ids(rights_df, "Future rights")
    if right_notes:
        st.warning("Check the ids — " + "; ".join(right_notes) + ".", icon="✏️")

st.subheader("3 · Transaction")
tx_raw: dict = doc.get("transaction") or {}
c1, c2, c3 = st.columns(3)
party_options = [NONE] + ids


def _pick(label: str, current: str | None, key: str, help: str) -> str | None:
    index = party_options.index(current) if current in party_options else 0
    value = st.selectbox(label, party_options, index=index, key=key, help=help, format_func=_entity_label)
    return None if value == NONE else value


def _entity_label(entity_id: str) -> str:
    """Show the full name beside the id, so the short id need not explain itself."""
    if entity_id == NONE:
        return NONE
    name = names.get(entity_id, "")
    return f"{name} ({entity_id})" if name and name != entity_id else entity_id


names = {str(r["id"]).strip(): str(r["name"]).strip() for r in entities_df.to_dict("records")
         if isinstance(r.get("id"), str) and isinstance(r.get("name"), str)}

with c1:
    buyer = _pick("Buyer", doc.get("buyer"), f"buyer_{v}",
                  "The person taking the action: the acquirer whose status is tested.")
with c2:
    target = _pick("Target", doc.get("target"), f"target_{v}",
                   "The Australian entity, business or tenement the action relates to.")
with c3:
    actions = [a.value for a in Action]
    current_action = tx_raw.get("action", Action.ACQUIRE_INTEREST.value)
    action = st.selectbox(
        "Action", actions, index=actions.index(current_action) if current_action in actions else 0,
        format_func=lambda a: a.replace("_", " ").capitalize(), key=f"action_{v}",
        help="Acquire interest: FATR s 56(1)(a) and (c)(ii). Start business: s 56(1)(b). "
             "Acquire tenement: s 56(1)(c)(i).")

defaults = Transaction()
tx: dict = {"action": action}
col_facts, col_exceptions = st.columns(2)
for column, heading, flags in ((col_facts, "Facts", FACT_FLAGS),
                               (col_exceptions, "Exceptions (FATR s 56)", EXCEPTION_FLAGS)):
    with column:
        st.markdown(f"**{heading}**")
        for name, (label, tip) in flags.items():
            value = st.checkbox(label, value=bool(tx_raw.get(name, getattr(defaults, name))),
                                key=f"{name}_{v}", help=tip)
            if value != getattr(defaults, name):
                tx[name] = value
tx_note = st.text_input("Transaction note", tx_raw.get("note", ""), key=f"tx_note_{v}")
if tx_note:
    tx["note"] = tx_note


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _records(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records")


st.divider()
st.header("Result")

header = {"title": title or "Untitled structure", "buyer": buyer, "target": target,
          "transaction": tx if buyer else None}
try:
    data = from_rows(_records(entities_df), _records(holdings_df), _records(rights_df), header)
    graph = from_dict(data)
except (InputError, ValueError, TypeError) as exc:
    st.error(f"The input cannot be read yet: {exc}")
    st.stop()

if not graph.entities:
    st.info("Add the entities in table 1 to start. Or load an example from the sidebar.")
    st.stop()

errors = [i for i in graph.validate() if i.level == "error"]
if errors:
    st.error("Fix these before the analysis can run:\n\n" + "\n".join(f"- {i.message}" for i in errors))
    st.stop()

findings = determine_fgi(graph)
decision = assess(graph) if graph.buyer else None
report = render_markdown(graph)

pending = uncertain_entities(graph)
provisional = " (provisional)" if pending else ""

if decision is None:
    st.info("No buyer selected: showing foreign government investor status only.")
elif decision.notifiable:
    st.error(f"**Notifiable{provisional}.** FIRB approval is required before {graph.entities[graph.buyer].name} "
             "takes this action.\n\n" + "\n".join(f"- {t}" for t in decision.triggers))
elif pending:
    st.warning("**Not notifiable — provisional.** Do not rely on this yet: see below.")
else:
    st.success("**Not notifiable under FATR s 56** on the facts entered, subject to the matters for human judgment.")
if pending:
    st.warning(f"**Provisional.** {provisional_note(graph, pending)}", icon="⚖️")

if decision is not None:
    m1, m2, m3 = st.columns(3)
    m1.metric("Buyer is a foreign government investor",
              ("Yes" if decision.buyer_is_fgi else "No") + provisional)
    if decision.buyer_finding:
        m1.caption(decision.buyer_finding.provision)
    if decision.after is not None:
        m2.metric("Interest in target before", f"{decision.before.pct:g}%")
        m3.metric("Interest in target after", f"{decision.after.pct:g}%",
                  f"{decision.after.pct - decision.before.pct:+g} pts", delta_color="off")

tab_report, tab_diagram = st.tabs(["Report", "Structure diagram"])
with tab_report:
    # Streamlit does not draw Mermaid, so the diagram is shown in its own tab instead.
    shown = re.sub(r"## Ownership structure.*?```mermaid.*?```\n", "", report, flags=re.S)
    shown = re.sub(r"^(#{1,4}) ", lambda m: "#" * (len(m.group(1)) + 2) + " ", shown, flags=re.M)
    st.markdown(shown)
with tab_diagram:
    st.caption("Shaded: government bodies. Red border: foreign government investors. Dashed: proposed holdings.")
    st.graphviz_chart(to_dot(graph, findings), width="content")

slug = re.sub(r"[^A-Za-z0-9]+", "-", graph.title).strip("-").lower()[:60] or "structure"
st.download_button("Download report (Markdown)", report, file_name=f"{slug}-report.md")
