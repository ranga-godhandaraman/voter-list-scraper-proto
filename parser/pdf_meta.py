"""Optional PDF metadata analysis for authorized sample files only.

This module never downloads electoral-roll PDFs from the gateway.
It only analyzes files already present on disk (e.g. manually saved samples).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class PdfMetadata:
    path: str
    size_bytes: int
    page_count: int | None
    encrypted: bool | None
    metadata: dict[str, Any]
    text_extractable: bool
    notes: str


def analyze_local_pdf(path: Path) -> PdfMetadata:
    """Analyze a local PDF file with pypdf (no network)."""
    from pypdf import PdfReader

    size = path.stat().st_size
    reader = PdfReader(str(path))
    encrypted = bool(reader.is_encrypted)
    meta = {}
    if reader.metadata:
        meta = {k: str(v) for k, v in dict(reader.metadata).items()}
    text_ok = False
    notes = []
    try:
        if reader.pages:
            sample = reader.pages[0].extract_text() or ""
            text_ok = len(sample.strip()) > 40
            notes.append("text_layer" if text_ok else "likely_scanned_or_image_heavy")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"text_extract_error:{exc}")

    result = PdfMetadata(
        path=str(path),
        size_bytes=size,
        page_count=len(reader.pages),
        encrypted=encrypted,
        metadata=meta,
        text_extractable=text_ok,
        notes="; ".join(notes),
    )
    logger.info("PDF meta {}: pages={} text={}", path.name, result.page_count, text_ok)
    return result


def analyze_samples(directory: Path) -> list[dict[str, Any]]:
    """Analyze all PDFs under a local directory (manual samples only)."""
    if not directory.exists():
        return []
    out: list[dict[str, Any]] = []
    for pdf in sorted(directory.glob("**/*.pdf")):
        try:
            out.append(asdict(analyze_local_pdf(pdf)))
        except Exception as exc:  # noqa: BLE001
            out.append({"path": str(pdf), "error": str(exc)})
    return out
