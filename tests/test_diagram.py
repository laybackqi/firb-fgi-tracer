"""Tests for the DOT diagram used by the web app."""

from pathlib import Path

from firb_tracer.diagram import FGI_BORDER, to_dot
from firb_tracer.fgi import determine_fgi
from firb_tracer.model import load_yaml

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_offshore_example_diagram():
    graph = load_yaml(EXAMPLES / "hk_holdco_miner.yaml")
    dot = to_dot(graph, determine_fgi(graph))
    assert dot.startswith("digraph structure {") and dot.rstrip().endswith("}")
    assert '"City-SZ_SOE" -> "HK_HoldCo" [label="25%", style=dashed' in dot  # proposed holding
    assert '"HK_HoldCo" -> "AU_Miner" [label="12%"]' in dot
    assert "[FGI]" in dot and "[FG]" in dot and "target" in dot
    assert dot.count(f'color="{FGI_BORDER}", penwidth=2.5') == 3  # SASAC, SOE and holdco


def test_quotes_in_names_are_escaped():
    graph = load_yaml(EXAMPLES / "t04_same_country.yaml")
    graph.entities["Company-D"].name = 'D "Holdings" Co'
    assert 'label="D \\"Holdings\\" Co' in to_dot(graph, determine_fgi(graph))
