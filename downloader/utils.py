"""Filename / path helpers for the downloader."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WS = re.compile(r"\s+")


def safe_name(text: str, *, max_len: int = 120) -> str:
    """Make a filesystem-safe single path component."""
    cleaned = _ILLEGAL.sub("_", (text or "").strip())
    cleaned = _WS.sub("_", cleaned)
    cleaned = cleaned.strip("._ ")
    if not cleaned:
        cleaned = "unknown"
    return cleaned[:max_len]


def part_filename(part_number: str, part_name: str | None = None, language: str | None = None) -> str:
    """Build Part_0001.pdf style name (optionally include name/lang)."""
    try:
        num = int(str(part_number).strip())
        prefix = f"Part_{num:04d}"
    except ValueError:
        prefix = f"Part_{safe_name(str(part_number))}"
    bits = [prefix]
    if part_name:
        bits.append(safe_name(part_name, max_len=60))
    if language:
        bits.append(safe_name(language, max_len=10))
    return "_".join(bits) + ".pdf"


def build_rel_path(
    *,
    state_short: str,
    year: str,
    district_name: str,
    ac_name: str,
    filename: str,
    language: str | None = None,
) -> Path:
    """downloads/AP/2025/District/Assembly[/LANG]/Part_0001.pdf."""
    parts = [
        safe_name(state_short),
        safe_name(year),
        safe_name(district_name),
        safe_name(ac_name),
    ]
    if language:
        parts.append(safe_name(language))
    return Path(*parts) / filename


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def classify_roll_kind(value: str, label: str) -> str:
    """Best-effort FIR/DR/SUPP classification from SPA option value/label."""
    blob = f"{value} {label}".upper()
    # Check Draft before Final — labels like "SIR DraftRoll" must not be misclassified
    if "DRAFT" in blob or re.search(r"(^|[^A-Z])DR([^A-Z]|$)", blob):
        return "DR"
    if "FIR" in blob or "FINAL" in blob:
        return "FIR"
    if "SUPP" in blob or "SUPPLEMENT" in blob:
        return "SUPP"
    return "OTHER"
