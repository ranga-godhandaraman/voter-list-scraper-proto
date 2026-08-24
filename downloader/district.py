"""District name resolution for CLI-driven downloads."""

from __future__ import annotations

import re
import unicodedata

from downloader.models import DistrictInfo


def normalize_name(text: str) -> str:
    """Lowercase, strip accents/punctuation for fuzzy matching."""
    text = unicodedata.normalize("NFKD", (text or "").strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def score_district_match(query: str, candidate: str) -> int:
    """Higher is better. 0 means no match."""
    q = normalize_name(query)
    c = normalize_name(candidate)
    if not q or not c:
        return 0
    if q == c:
        return 100
    if c.startswith(q) or q.startswith(c):
        return 80
    if q in c or c in q:
        return 60
    q_tokens = set(q.split())
    c_tokens = set(c.split())
    overlap = len(q_tokens & c_tokens)
    if overlap:
        return 40 + overlap * 10
    return 0


def list_district_matches(
    districts: list[DistrictInfo], query: str, *, limit: int = 10
) -> list[tuple[DistrictInfo, int]]:
    scored = [
        (d, score_district_match(query, d.district_name))
        for d in districts
    ]
    scored = [(d, s) for d, s in scored if s > 0]
    scored.sort(key=lambda x: (-x[1], x[0].district_name))
    return scored[:limit]


def resolve_district_by_name(
    districts: list[DistrictInfo], query: str
) -> DistrictInfo:
    matches = list_district_matches(districts, query, limit=5)
    if not matches:
        names = ", ".join(d.district_name for d in districts[:12])
        raise KeyError(
            f"No district matching {query!r}. "
            f"Examples in this state: {names}…"
        )
    best, best_score = matches[0]
    if len(matches) > 1 and matches[1][1] == best_score:
        options = "\n".join(
            f"  {i}. {d.district_name} ({d.district_cd})"
            for i, (d, _) in enumerate(matches, start=1)
        )
        raise KeyError(
            f"Ambiguous district {query!r}. Multiple matches:\n{options}\n"
            "Re-run with a more specific --district name."
        )
    return best
