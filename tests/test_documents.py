"""Tests for turning uploaded files into text."""

import io

import pytest

docx = pytest.importorskip("docx")
pypdf = pytest.importorskip("pypdf")

from firb_tracer.documents import DocumentError, extract_text  # noqa: E402
from firb_tracer.text_rules import read_text  # noqa: E402


def _docx_bytes() -> bytes:
    doc = docx.Document()
    doc.add_paragraph("深圳市国资委持有甲公司100%股权。")
    doc.add_paragraph("乙公司股东情况如下：")
    table = doc.add_table(rows=3, cols=4)
    for row, cells in zip(table.rows, [("序号", "股东名称", "认缴出资（万元）", "持股比例"),
                                       ("1", "甲公司", "500", "25%"),
                                       ("2", "丙公司", "1,500", "75%")]):
        for cell, text in zip(row.cells, cells):
            cell.text = text
    doc.add_paragraph("甲公司拟收购乙公司15%股权。")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_docx_paragraphs_and_shareholder_table_in_order():
    text = extract_text("summary.docx", _docx_bytes())
    assert text.splitlines()[:4] == ["深圳市国资委持有甲公司100%股权。", "乙公司股东情况如下：", "甲公司 25%", "丙公司 75%"]
    x = read_text(text)
    assert {(h.holder, h.held, h.pct, h.proposed) for h in x.holdings} == {
        ("深圳市国资委", "甲公司", 100.0, False), ("甲公司", "乙公司", 25.0, False),
        ("丙公司", "乙公司", 75.0, False), ("甲公司", "乙公司", 15.0, True)}


def test_text_files_in_utf8_and_gb18030():
    assert extract_text("a.txt", "甲公司持有乙公司25%股权".encode("utf-8")) == "甲公司持有乙公司25%股权"
    assert extract_text("a.txt", "甲公司持有乙公司25%股权".encode("gb18030")) == "甲公司持有乙公司25%股权"


def test_scanned_pdf_is_refused_with_a_reason():
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(DocumentError, match="no text layer"):
        extract_text("scan.pdf", buf.getvalue())


@pytest.mark.parametrize("name, message", [("old.doc", "save it as .docx"), ("x.xlsx", "unsupported")])
def test_unsupported_files(name, message):
    with pytest.raises(DocumentError, match=message):
        extract_text(name, b"data")


def test_corrupt_docx():
    with pytest.raises(DocumentError, match="could not read"):
        extract_text("broken.docx", b"not a zip")
