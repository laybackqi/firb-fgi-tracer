"""Step 7 of the decision flow: a report a lawyer can read.

The report has three parts, kept apart on purpose (rules document, step 7):

1. Statutory conclusions: what the rules give, each with its chain of
   reasoning and the provisions relied on.
2. Matters for human judgment: everything the tool could not decide.
3. Risk signals: points for the merits review, with no conclusion drawn (R19).

It ends with a diagram of the structure in Mermaid, which GitHub and most
Markdown viewers draw as a picture.
"""

from __future__ import annotations

from .fgi import Finding, determine_fgi
from .model import OwnershipGraph
from .notification import Decision, assess

LEGISLATION = (
    "Foreign Acquisitions and Takeovers Act 1975, Compilation No. 35 (C2025C00672, in force 5 December 2025); "
    "Foreign Acquisitions and Takeovers Regulation 2015, Compilation No. 20 (F2025C01038, in force 1 November 2025)."
)

DISCLAIMER = (
    "This report is produced by a screening tool. It applies the jurisdictional rules described in the "
    "project's rules document to the facts entered, and does not assess the national interest. "
    "It is not legal advice."
)


def _name(graph: OwnershipGraph, entity_id: str) -> str:
    entity = graph.entities.get(entity_id)
    return entity.name if entity else entity_id


def explain_fgi(graph: OwnershipGraph, findings: dict[str, Finding], entity_id: str, depth: int = 0) -> list[str]:
    """The chain of reasoning that makes an entity a foreign government investor."""
    f = findings.get(entity_id)
    indent = "  " * depth
    name = _name(graph, entity_id)
    if f is None:
        return [f"{indent}- {name} is not a foreign government investor."]
    if f.provision == "FATR s 17(1)(a)":
        e = graph.entities[entity_id]
        kind = {"FG": "foreign government", "SGE": "separate government entity"}[e.gov_status.value]
        reason = f" ({e.gov_reason})" if e.gov_reason else ""
        return [f"{indent}- {name} is a {kind} in relation to {e.country}: {f.provision}{reason}."]

    others = [m for m in f.members if m != f.via]
    if f.via:
        holder = _name(graph, f.via)
        if others:
            parts = [f"{_name(graph, m)} ({f.members[m]})" for m in others]
            holder += ", together with " + "; ".join(parts) + ","
        holds = "holds"
    else:
        holder = "Governments of " + ", ".join(sorted(f.countries))
        holds = "together hold"
    status = "is a foreign government investor" if f.is_fgi else "is not a foreign government investor"
    lines = [f"{indent}- {name} {status}: {f.provision}. {holder} {holds} {f.pct:g}% of it, "
             f"measured by {f.limb}."]
    if f.exemption:
        lines.append(f"{indent}  - FATR s 17(2) exception: {f.exemption}.")
    if f.via:
        lines.extend(explain_fgi(graph, findings, f.via, depth + 1))
    return lines


def _mermaid(graph: OwnershipGraph, findings: dict[str, Finding]) -> list[str]:
    ids = {eid: f"n{i}" for i, eid in enumerate(graph.entities)}
    lines = ["```mermaid", "flowchart TD"]
    for eid, entity in graph.entities.items():
        f = findings.get(eid)
        if entity.is_government:
            tag = entity.gov_status.value
        elif f is not None and f.is_fgi:
            tag = "FGI"
        else:
            tag = ""
        label = entity.name.replace('"', "'") + (f"<br/>[{tag}]" if tag else "")
        shape = f'(["{label}"])' if eid == graph.target else f'["{label}"]'
        lines.append(f"  {ids[eid]}{shape}")
    for h in graph.holdings:
        pct = h.shares_pct or h.distribution_pct or h.voting_pct or 0
        extra = []
        if h.veto:
            extra.append("veto")
        if h.board_seats:
            extra.append(f"board {h.board_seats}")
        label = f"{pct:g}%" + (", " + ", ".join(extra) if extra else "")
        arrow = "-.->" if h.proposed else "-->"
        lines.append(f'  {ids[h.holder]} {arrow}|"{label}"| {ids[h.held]}')
    for eid, f in findings.items():
        if f.is_fgi and eid in ids:
            lines.append(f"  style {ids[eid]} stroke-width:3px")
    lines.append("```")
    return lines


def render_markdown(graph: OwnershipGraph) -> str:
    """The full report for a structure with a buyer and a transaction."""
    findings = determine_fgi(graph)
    issues = graph.validate()
    errors = [i for i in issues if i.level == "error"]
    out: list[str] = [f"# FIRB screening report: {graph.title}", ""]

    if errors:
        out += ["## The input has errors", "", "Fix these before the analysis can run:", ""]
        out += [f"- {i.message}" for i in errors]
        return "\n".join(out) + "\n"

    decision: Decision | None = assess(graph) if graph.buyer else None

    # --- Conclusion ----------------------------------------------------------
    out += ["## Conclusion", ""]
    if decision is None:
        out.append("No buyer is named, so only foreign government investor status is assessed.")
    elif decision.notifiable:
        out.append(f"**Notifiable.** The proposed action by {_name(graph, graph.buyer)} is a significant "
                   "and notifiable action. FIRB approval is required before it is taken.")
    else:
        out.append(f"**Not notifiable under FATR s 56** on the facts entered, subject to the matters "
                   "for human judgment below.")
    out.append("")

    # --- Part 1 --------------------------------------------------------------
    out += ["## 1. Statutory conclusions", ""]
    if decision is not None:
        out += ["### The buyer", ""]
        out += explain_fgi(graph, findings, graph.buyer)
        out.append("")
        if decision.after is not None:
            out += ["### The buyer's interest in the target", ""]
            out.append(f"Before the action: **{decision.before.pct:g}%**. After the action: **{decision.after.pct:g}%** "
                       f"(measured by {decision.after.limb}).")
            out += ["", "| Holder of target shares | Interest | Why it counts |", "| --- | --- | --- |"]
            for holder, pct in decision.after.blocks.items():
                out.append(f"| {_name(graph, holder)} | {pct:g}% | {decision.after.attributed[holder]} |")
            out.append("")
            out.append("Each holding in the target is counted once, however many routes lead to it (R14).")
            out.append("")
        out += ["### Notification", ""]
        out += [f"- {line}" for line in decision.reasoning]
        out += [f"- Triggered: {t}." for t in decision.triggers]
        out += [f"- Exception applied: {e}." for e in decision.exceptions]
        out.append("")

    others = [eid for eid, f in findings.items()
              if f.provision != "FATR s 17(1)(a)" and eid != graph.buyer]
    if others:
        out += ["### Other foreign government investors in the structure", ""]
        for eid in others:
            out += explain_fgi(graph, findings, eid)
        out.append("")

    # --- Part 2 --------------------------------------------------------------
    out += ["## 2. Matters for human judgment", ""]
    review = [i.message for i in issues if i.level == "warning"]
    review += [f"{_name(graph, eid)}: {f.exemption}" for eid, f in findings.items()
               if f.exemption.startswith("possible")]
    if decision is not None:
        review += decision.review
    out += [f"- {r}" for r in dict.fromkeys(review)] or ["- None."]
    out.append("")

    # --- Part 3 --------------------------------------------------------------
    out += ["## 3. Risk signals for the national interest review", "",
            "The tool draws no conclusion on these (R19).", ""]
    signals = []
    if graph.transaction and graph.transaction.target_is_mining_entity:
        signals.append("The target is a mining, production or exploration entity.")
    if any(h.veto for h in graph.holdings):
        signals.append("A government holder has a veto, which may show influence beyond its shareholding.")
    if any(e.control_indicators for e in graph.entities.values()):
        signals.append("Non-equity control indicators were recorded (for example cadre appointment or "
                       "Party committee pre-review).")
    signals.append("Whether the target carries on a sensitive business or a national security business "
                   "has not been assessed.")
    out += [f"- {s}" for s in signals]
    out.append("")

    # --- Diagram and sources -------------------------------------------------
    out += ["## Ownership structure", "",
            "Dashed arrows are proposed holdings; thick borders are foreign government investors.", ""]
    out += _mermaid(graph, findings)
    out += ["", "## Basis", "", f"- Legislation: {LEGISLATION}",
            "- Sources of figures: as recorded against each holding in the input.",
            f"- {DISCLAIMER}", ""]
    return "\n".join(out)
