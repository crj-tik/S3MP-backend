"""Bounded text extraction for the v1 document formats (without OCR)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from docx import Document
from openpyxl import load_workbook  # type: ignore[import-untyped]
from pptx import Presentation
from pypdf import PdfReader


class UnsupportedDocumentType(ValueError):
    """The source is not one of the explicitly supported v1 formats."""


class ExtractionLimitExceeded(ValueError):
    """Extraction exceeded a configured safety bound."""


class OcrRequiredDocument(UnsupportedDocumentType):
    """A PDF has no extractable text and OCR is intentionally unavailable."""


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    format: str
    segments: tuple[EvidenceSegment, ...]


@dataclass(frozen=True)
class EvidenceSegment:
    """Normalized source text plus a location usable in card provenance."""

    text: str
    location: dict[str, str | int]


@dataclass(frozen=True)
class EvidenceChunk:
    """A model-input chunk retaining every contributing evidence location."""

    text: str
    locations: tuple[dict[str, str | int], ...]


def extract_text(
    body: bytes,
    *,
    filename: str,
    content_type: str | None,
    max_characters: int,
) -> ExtractedDocument:
    """Extract visible textual content; images and OCR are deliberately excluded."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    normalized_type = (content_type or "").lower().split(";", 1)[0].strip()
    if suffix == "pdf" or normalized_type == "application/pdf":
        segments = tuple(
            EvidenceSegment(page_text, {"page": page_number})
            for page_number, page in enumerate(PdfReader(io.BytesIO(body)).pages, start=1)
            if (page_text := _normalize_text(page.extract_text() or ""))
        )
        text = "\n\n".join(segment.text for segment in segments)
        document_format = "pdf"
    elif suffix == "docx" or normalized_type.endswith("wordprocessingml.document"):
        document = Document(io.BytesIO(body))
        paragraph_segments = tuple(
            EvidenceSegment(paragraph_text, {"paragraph": paragraph_number})
            for paragraph_number, paragraph in enumerate(document.paragraphs, start=1)
            if (paragraph_text := _normalize_text(paragraph.text))
        )
        table_segments = tuple(
            EvidenceSegment(row_text, {"table": table_number, "row": row_number})
            for table_number, table in enumerate(document.tables, start=1)
            for row_number, row in enumerate(table.rows, start=1)
            if (row_text := _normalize_text(" | ".join(cell.text for cell in row.cells)))
        )
        segments = paragraph_segments + table_segments
        text = "\n\n".join(segment.text for segment in segments)
        document_format = "docx"
    elif suffix == "xlsx" or normalized_type.endswith("spreadsheetml.sheet"):
        workbook = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
        parts: list[str] = []
        extracted_segments: list[EvidenceSegment] = []
        for sheet in workbook.worksheets:
            parts.append(f"# {sheet.title}")
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = [str(value) for value in row if value is not None]
                if values:
                    row_text = " | ".join(values)
                    parts.append(row_text)
                    extracted_segments.append(
                        EvidenceSegment(row_text, {"sheet": sheet.title, "row": row_number})
                    )
        text, document_format = "\n".join(parts), "xlsx"
        segments = tuple(extracted_segments)
    elif suffix == "pptx" or normalized_type.endswith("presentationml.presentation"):
        presentation = Presentation(io.BytesIO(body))
        ppt_parts: list[str] = []
        extracted_segments = []
        for number, slide in enumerate(presentation.slides, start=1):
            ppt_parts.append(f"# Slide {number}")
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    shape_text = _normalize_text(shape.text)
                    if shape_text:
                        ppt_parts.append(shape_text)
                        extracted_segments.append(EvidenceSegment(shape_text, {"slide": number}))
        text, document_format = "\n".join(ppt_parts), "pptx"
        segments = tuple(extracted_segments)
    elif suffix in {"md", "markdown"} or normalized_type in {"text/markdown", "text/x-markdown"}:
        text, document_format = body.decode("utf-8", errors="replace"), "markdown"
        segments = _paragraph_segments(text, "paragraph")
    elif suffix in {"html", "htm"} or normalized_type in {"text/html", "application/xhtml+xml"}:
        parser = _VisibleTextParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        text, document_format = parser.text(), "html"
        segments = _paragraph_segments(text, "dom_text")
    else:
        raise UnsupportedDocumentType(
            f"unsupported source format: {suffix or normalized_type or 'unknown'}"
        )
    normalized = _normalize_text(text)
    if document_format == "pdf" and not normalized:
        raise OcrRequiredDocument("PDF has no extractable text; OCR is not enabled")
    if len(normalized) > max_characters:
        raise ExtractionLimitExceeded("extracted text exceeds configured character limit")
    return ExtractedDocument(text=normalized, format=document_format, segments=segments)


def chunk_text(text: str, *, max_characters: int) -> list[str]:
    """Split at paragraph boundaries where possible, preserving all content."""
    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    if not text:
        return []
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > max_characters:
            chunks.append(current)
            current = ""
        while len(paragraph) > max_characters:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:max_characters])
            paragraph = paragraph[max_characters:]
        current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def chunk_segments(
    segments: tuple[EvidenceSegment, ...], *, max_characters: int
) -> tuple[EvidenceChunk, ...]:
    """Chunk only between evidence units; never silently split a source unit."""
    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    chunks: list[EvidenceChunk] = []
    text_parts: list[str] = []
    locations: list[dict[str, str | int]] = []
    current_size = 0
    for segment in segments:
        if len(segment.text) > max_characters:
            raise ExtractionLimitExceeded("one evidence segment exceeds the configured chunk limit")
        separator = 2 if text_parts else 0
        if text_parts and current_size + separator + len(segment.text) > max_characters:
            chunks.append(EvidenceChunk("\n\n".join(text_parts), tuple(locations)))
            text_parts, locations, current_size = [], [], 0
        text_parts.append(segment.text)
        locations.append(segment.location)
        current_size += separator + len(segment.text)
    if text_parts:
        chunks.append(EvidenceChunk("\n\n".join(text_parts), tuple(locations)))
    return tuple(chunks)


class _VisibleTextParser(HTMLParser):
    _hidden_tags = {"code", "pre", "script", "style", "template", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._hidden_tags:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._hidden_tags and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(self._parts)


def _normalize_text(value: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", value)).strip()


def _paragraph_segments(text: str, location_key: str) -> tuple[EvidenceSegment, ...]:
    return tuple(
        EvidenceSegment(normalized, {location_key: number})
        for number, paragraph in enumerate(text.split("\n\n"), start=1)
        if (normalized := _normalize_text(paragraph))
    )
