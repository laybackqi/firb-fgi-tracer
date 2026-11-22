"""The ownership structure as a Graphviz DOT diagram.

The Markdown report draws the structure in Mermaid, which GitHub renders.
The web app draws it in DOT instead, because Streamlit renders DOT natively
(st.graphviz_chart) with no extra package and no external script.

Both diagrams follow the same conventions:

* governments (FG / SGE) are shaded; foreign government investors have a
  thick red border;
* the target is drawn with rounded corners;
* proposed holdings are dashed.
"""

from __future__ import annotations

from .fgi import Finding
from .model import OwnershipGraph

GOV_FILL = "#E8EEF7"
FGI_BORDER = "#B42318"


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def edge_label(h) -> str:
    """The percentage shown on an arrow, with any veto or board seats."""
    pct = h.shares_pct or h.distribution_pct or h.voting_pct or 0
    extra = []
    if h.veto:
        extra.append("veto")
    if h.board_seats:
        extra.append(f"board {h.board_seats}")
    return f"{pct:g}%" + (", " + ", ".join(extra) if extra else "")


def to_dot(graph: OwnershipGraph, findings: dict[str, Finding]) -> str:
    """A DOT digraph of the structure, top (owners) to bottom (target)."""
    lines = [
        "digraph structure {",
        '  graph [rankdir=TB, nodesep=0.5, ranksep=0.6, fontname="Helvetica"];',
        '  node [shape=box, style="filled", fillcolor="white", fontname="Helvetica", fontsize=11, margin="0.15,0.08"];',
        '  edge [fontname="Helvetica", fontsize=10, color="#555555"];',
    ]
    for eid, entity in graph.entities.items():
        f = findings.get(eid)
        tag = ""
        attrs: dict[str, str] = {}
        if entity.is_government:
            tag = entity.gov_status.value
            attrs["fillcolor"] = _quote(GOV_FILL)
        elif f is not None and f.is_fgi:
            tag = "FGI"
        if f is not None and f.is_fgi:
            attrs["color"] = _quote(FGI_BORDER)
            attrs["penwidth"] = "2.5"
        if eid == graph.target:
            attrs["style"] = '"filled,rounded"'
            tag = (tag + " · " if tag else "") + "target"
        label = entity.name + (f"\n[{tag}]" if tag else "")
        attrs["label"] = _quote(label)
        attr_text = ", ".join(f"{k}={v}" for k, v in attrs.items())
        lines.append(f"  {_quote(eid)} [{attr_text}];")
    for h in graph.holdings:
        attrs = {"label": _quote(edge_label(h))}
        if h.proposed:
            attrs["style"] = "dashed"
            attrs["color"] = _quote(FGI_BORDER)
        attr_text = ", ".join(f"{k}={v}" for k, v in attrs.items())
        lines.append(f"  {_quote(h.holder)} -> {_quote(h.held)} [{attr_text}];")
    lines.append("}")
    return "\n".join(lines)
