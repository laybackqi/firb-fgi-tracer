"""Tests for the report and the command line."""

from pathlib import Path

from firb_tracer.__main__ import main
from firb_tracer.model import load_yaml
from firb_tracer.report import render_markdown

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_offshore_example_report_has_conclusion_chain_and_diagram():
    report = render_markdown(load_yaml(EXAMPLES / "hk_holdco_miner.yaml"))
    assert "**Notifiable.**" in report
    # The buyer's status is explained back to the government.
    assert "FATR s 17(1)(b)(i)" in report
    assert "Shenzhen SASAC is a foreign government in relation to CN" in report
    # The interest goes from 0% to 12% by tracing, not 3%.
    assert "Before the action: **0%**. After the action: **12%**" in report
    assert "FATA s 19" in report
    # The three parts and the diagram are all there.
    for heading in ("## 1. Statutory conclusions", "## 2. Matters for human judgment",
                    "## 3. Risk signals", "```mermaid"):
        assert heading in report
    assert "-.->" in report  # the proposed holding is dashed
    assert "not legal advice" in report


def test_input_errors_stop_the_report():
    graph = load_yaml(EXAMPLES / "hk_holdco_miner.yaml")
    graph.entities["sz_sasac"].country = None
    report = render_markdown(graph)
    assert "## The input has errors" in report
    assert "## Conclusion" not in report


def test_command_line_writes_a_file(tmp_path):
    out = tmp_path / "report.md"
    assert main([str(EXAMPLES / "hk_holdco_miner.yaml"), "-o", str(out)]) == 0
    assert "**Notifiable.**" in out.read_text(encoding="utf-8")
