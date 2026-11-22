"""Plain text out of an uploaded Word, PDF or text file.

The text readers work on plain text, so an uploaded file is turned into text
first. No outside service is used.

* Word (.docx): paragraphs and tables, in document order. Each table row
  becomes one line. Cells holding only a number (a row number, a capital
  amount) are dropped, so a shareholder table row such as
  "1 | 甲公司 | 500 | 60%" becomes "甲公司 60%", which the list reader can use.
* PDF: the text layer of each page. A scanned PDF has none, and needs OCR,
  which is out of scope.
* Text (.txt, .md): UTF-8, or GB18030 for files saved by Chinese Windows.

The old .doc format is not supported: save it as .docx first.
"""

from __future__ import annotations

import io
import re

MAX_BYTES = 10 * 1024 * 1024
NUMBER_ONLY = re.compile(r"^[\d.,\s]+(?:万元|元|万|亿元)?$")


class DocumentError(ValueError):
    """The file cannot be turned into text."""


def _row_line(cells: list[str]) -> str:
    kept: list[str] = []
    for text in cells:
        text = " ".join(text.split())
        if text and not NUMBER_ONLY.match(text) and text not in kept:  # merged cells repeat
            kept.append(text)
    return " ".join(kept)


def _docx(data: bytes) -> str:
    from docx import Document  # python-docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    lines: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            lines.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            for n, row in enumerate(Table(child, doc).rows):
                line = _row_line([cell.text for cell in row.cells])
                # A header row ("股东名称 持股比例") carries no figures: skip it.
                if n == 0 and not re.search(r"\d", line):
                    continue
                lines.append(line)
            lines.append("")  # a table ends any shareholder list
    return "\n".join(lines)


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        raise DocumentError("this PDF has no text layer (it may be a scan); copy the text in by hand")
    return text


def _plain(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentError("the file is not UTF-8 or GB18030 text")


def extract_text(filename: str, data: bytes) -> str:
    """The plain text of an uploaded file, chosen by its extension."""
    if len(data) > MAX_BYTES:
        raise DocumentError("the file is larger than 10 MB")
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if suffix == "docx":
            text = _docx(data)
        elif suffix == "pdf":
            text = _pdf(data)
        elif suffix in ("txt", "md"):
            text = _plain(data)
        elif suffix == "doc":
            raise DocumentError("the old .doc format is not supported; save it as .docx first")
        else:
            raise DocumentError(f"unsupported file type '.{suffix}'; use .docx, .pdf or .txt")
    except DocumentError:
        raise
    except Exception as exc:  # a corrupt or password-protected file
        raise DocumentError(f"could not read {filename}: {exc}") from exc
    return re.sub(r"\n{3,}", "\n\n", text).strip()
