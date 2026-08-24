"""ISO-style short codes ↔ ECI stateCd / official names.

Central mapping used by the downloader and any future modules.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StateInfo:
    """Canonical state / UT identity."""

    short_code: str
    name: str
    eci_state_cd: str  # e.g. S01, U05
    aliases: tuple[str, ...] = ()


# Short code → StateInfo (official display names per user mapping)
STATES: dict[str, StateInfo] = {
    "AP": StateInfo("AP", "Andhra Pradesh", "S01"),
    "AR": StateInfo("AR", "Arunachal Pradesh", "S02"),
    "AS": StateInfo("AS", "Assam", "S03"),
    "BR": StateInfo("BR", "Bihar", "S04"),
    "CG": StateInfo("CG", "Chhattisgarh", "S26", aliases=("Chattisgarh",)),
    "GA": StateInfo("GA", "Goa", "S05"),
    "GJ": StateInfo("GJ", "Gujarat", "S06"),
    "HR": StateInfo("HR", "Haryana", "S07"),
    "HP": StateInfo("HP", "Himachal Pradesh", "S08"),
    "JH": StateInfo("JH", "Jharkhand", "S27"),
    "KA": StateInfo("KA", "Karnataka", "S10"),
    "KL": StateInfo("KL", "Kerala", "S11"),
    "MP": StateInfo("MP", "Madhya Pradesh", "S12"),
    "MH": StateInfo("MH", "Maharashtra", "S13"),
    "MN": StateInfo("MN", "Manipur", "S14"),
    "ML": StateInfo("ML", "Meghalaya", "S15"),
    "MZ": StateInfo("MZ", "Mizoram", "S16"),
    "NL": StateInfo("NL", "Nagaland", "S17"),
    "OD": StateInfo("OD", "Odisha", "S18", aliases=("OR", "Orissa")),
    "PB": StateInfo("PB", "Punjab", "S19"),
    "RJ": StateInfo("RJ", "Rajasthan", "S20"),
    "SK": StateInfo("SK", "Sikkim", "S21"),
    "TN": StateInfo("TN", "Tamil Nadu", "S22"),
    "TG": StateInfo("TG", "Telangana", "S29", aliases=("TS",)),
    "TR": StateInfo("TR", "Tripura", "S23"),
    "UP": StateInfo("UP", "Uttar Pradesh", "S24"),
    "UK": StateInfo("UK", "Uttarakhand", "S28", aliases=("UT",)),
    "WB": StateInfo("WB", "West Bengal", "S25"),
    "AN": StateInfo("AN", "Andaman & Nicobar Islands", "U01"),
    "CH": StateInfo("CH", "Chandigarh", "U02"),
    "DN": StateInfo(
        "DN",
        "Dadra & Nagar Haveli and Daman & Diu",
        "U03",
        aliases=("DD", "DNHDD"),
    ),
    "DL": StateInfo("DL", "Delhi", "U05", aliases=("NCT OF Delhi", "NCT Of Delhi")),
    "JK": StateInfo("JK", "Jammu & Kashmir", "U08", aliases=("Jammu and Kashmir",)),
    "LA": StateInfo("LA", "Ladakh", "U09"),
    "LD": StateInfo("LD", "Lakshadweep", "U06"),
    "PY": StateInfo("PY", "Puducherry", "U07", aliases=("Pondicherry",)),
}

_BY_ECI: dict[str, StateInfo] = {s.eci_state_cd: s for s in STATES.values()}
_BY_NAME: dict[str, StateInfo] = {}
for s in STATES.values():
    _BY_NAME[s.name.casefold()] = s
    for a in s.aliases:
        _BY_NAME[a.casefold()] = s


def normalize_short_code(code: str) -> str:
    """Uppercase and strip a user-provided short code."""
    return (code or "").strip().upper()


def resolve_state(code_or_name: str) -> StateInfo:
    """Resolve AP / S01 / 'Andhra Pradesh' to StateInfo.

    Raises:
        KeyError: if the state cannot be resolved.
    """
    raw = (code_or_name or "").strip()
    if not raw:
        raise KeyError("Empty state code")

    upper = raw.upper()
    if upper in STATES:
        return STATES[upper]
    if upper in _BY_ECI:
        return _BY_ECI[upper]

    # Alias short codes (OR→OD, TS→TG, …)
    for info in STATES.values():
        if upper in {a.upper() for a in info.aliases if len(a) <= 5}:
            return info

    folded = raw.casefold()
    if folded in _BY_NAME:
        return _BY_NAME[folded]

    # Fuzzy: startswith / contains against official names
    for info in STATES.values():
        if info.name.casefold().startswith(folded) or folded in info.name.casefold():
            return info

    raise KeyError(
        f"Unknown state '{code_or_name}'. Use a short code like AP, TN, KA "
        f"(see downloader.state_mapping.STATES)."
    )


def list_short_codes() -> list[str]:
    """Sorted list of supported short codes."""
    return sorted(STATES.keys())


def eci_label_for_select(info: StateInfo) -> str:
    """Best-effort label text as shown in the SPA state dropdown."""
    # Portal uses "NCT OF Delhi" and "Jammu and Kashmir" / "Chattisgarh"
    overrides = {
        "DL": "NCT OF Delhi",
        "JK": "Jammu and Kashmir",
        "CG": "Chattisgarh",  # portal spelling
    }
    return overrides.get(info.short_code, info.name)
