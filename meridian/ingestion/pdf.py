"""PDF clause parsing with PyMuPDF.

Text-based synthetic PDFs only: encrypted, corrupt, scanned/image-only and
otherwise unsupported documents raise :class:`UnsupportedDocument` with an explicit
reason instead of silently ingesting empty text.  Parser output is preserved in the
clause table and committed through the Merkle tree; the parser version is pinned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

from ..contracts.common import PARSER_VERSION


class UnsupportedDocument(ValueError):
    """Raised for documents that must not be silently ingested."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True)
class ParsedClause:
    index: int
    page: int
    section: str | None
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class ParsedDocument:
    page_count: int
    clauses: list[ParsedClause]
    parser_version: str
    text_length: int
    warnings: list[str]

    def normalized_text(self) -> str:
        return "\n".join(clause.text for clause in self.clauses)


_HEADING = re.compile(r"^(?P<section>\d+(?:\.\d+)*)\s+(?P<title>[\w(].*)$")
_MIN_TEXT_CHARS = 40


def _clean_lines(page_text: str) -> list[str]:
    lines = [line.rstrip() for line in page_text.splitlines()]
    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        cleaned.append(line)
    return cleaned


def parse_pdf_bytes(data: bytes, *, parser_version: str = PARSER_VERSION) -> ParsedDocument:
    """Split a text-based PDF into clause records preserving exact parser text."""

    if not data:
        raise UnsupportedDocument("empty_file", "the supplied PDF is empty")
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # pragma: no cover - depends on malformed input
        raise UnsupportedDocument("corrupt_pdf", f"PyMuPDF could not open the file: {exc}") from exc

    with document:
        if not document.is_pdf:
            raise UnsupportedDocument("unsupported_format", "the supplied file is not a PDF")
        if document.needs_pass:
            raise UnsupportedDocument("encrypted_pdf", "password protected PDFs are out of scope")
        if document.page_count == 0:
            raise UnsupportedDocument("empty_pdf", "the PDF contains no pages")

        clauses: list[ParsedClause] = []
        current_lines: list[str] = []
        current_page = 1
        current_section: str | None = None
        total_chars = 0

        def flush() -> None:
            nonlocal current_lines
            text = "\n".join(current_lines).strip()
            current_lines = []
            if not text:
                return
            clauses.append(
                ParsedClause(
                    index=len(clauses),
                    page=current_page,
                    section=current_section,
                    text=text,
                    start_char=0,
                    end_char=len(text),
                )
            )

        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            page_number = page_index + 1
            page_text = page.get_text("text")
            total_chars += len(page_text)
            for line in _clean_lines(page_text):
                stripped = line.strip()
                if not stripped:
                    if current_lines:
                        current_lines.append("")
                    continue
                heading = _HEADING.match(stripped)
                if heading and len(stripped) <= 96:
                    flush()
                    current_page = page_number
                    current_section = heading.group("section")
                    current_lines = [stripped]
                    continue
                if not current_lines and page_number != current_page:
                    current_page = page_number
                current_lines.append(stripped)
            flush()
            current_page = page_number + 1

        if total_chars < _MIN_TEXT_CHARS or not clauses:
            raise UnsupportedDocument(
                "no_extractable_text",
                "no selectable text was found; scanned documents and OCR are out of scope",
            )

        return ParsedDocument(
            page_count=document.page_count,
            clauses=clauses,
            parser_version=parser_version,
            text_length=total_chars,
            warnings=[],
        )
