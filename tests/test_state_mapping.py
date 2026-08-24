"""Unit tests for state mapping and path helpers."""

from __future__ import annotations

import pytest

from downloader.state_mapping import resolve_state, list_short_codes
from downloader.utils import build_rel_path, classify_roll_kind, part_filename, safe_name


def test_resolve_short_codes() -> None:
    assert resolve_state("AP").eci_state_cd == "S01"
    assert resolve_state("tn").name == "Tamil Nadu"
    assert resolve_state("DL").eci_state_cd == "U05"
    assert resolve_state("S24").short_code == "UP"


def test_aliases() -> None:
    assert resolve_state("OR").short_code == "OD"
    assert resolve_state("TS").short_code == "TG"
    assert resolve_state("Jammu and Kashmir").short_code == "JK"


def test_list_codes_complete() -> None:
    codes = list_short_codes()
    assert "AP" in codes and "PY" in codes
    assert len(codes) == 36


def test_safe_filename() -> None:
    assert "Part_0001" in part_filename("1", "SILERU", "ENG")
    assert "/" not in safe_name('a/b<>c')
    rel = build_rel_path(
        state_short="AP",
        year="2025",
        district_name="Guntur",
        ac_name="Paderu",
        filename="Part_0001.pdf",
        language="ENG",
    )
    assert str(rel).startswith("AP/2025/")


def test_roll_kind() -> None:
    assert classify_roll_kind("S01-2025-FIR", "Final Roll - 2025") == "FIR"
    assert classify_roll_kind("S01-2025-DR", "Draft Roll - 2025") == "DR"
    assert classify_roll_kind("S06-2026-FIR", "SIR FinalRoll - 2026") == "FIR"
    assert classify_roll_kind("S06-2026-DR", "SIR DraftRoll - 2026") == "DR"


def test_resolve_district() -> None:
    from downloader.district import resolve_district_by_name
    from downloader.models import DistrictInfo

    districts = [
        DistrictInfo(district_cd="S0607", district_name="Ahmedabad", state_cd="S06"),
        DistrictInfo(district_cd="S0608", district_name="Amreli", state_cd="S06"),
    ]
    d = resolve_district_by_name(districts, "ahmedabad")
    assert d.district_name == "Ahmedabad"


def test_prefer_sir_draft_over_final() -> None:
    from downloader.discovery import pick_preferred_roll
    from downloader.models import RollTypeInfo

    rolls = [
        RollTypeInfo(
            value="S06-2026-FIR",
            label="SIR FinalRoll - 2026",
            year="2026",
            kind="FIR",
        ),
        RollTypeInfo(
            value="S06-2026-DR",
            label="SIR DraftRoll - 2026",
            year="2026",
            kind="DR",
        ),
    ]
    picked = pick_preferred_roll(rolls, ["DR", "DRAFT", "FIR", "FINAL"])
    assert picked is not None
    assert picked.value == "S06-2026-DR"
