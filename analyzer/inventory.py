"""Hierarchy inventory across States → Districts → Assembly Constituencies."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from network.gateway import GatewayProbe
from utils.config import Settings, get_settings


@dataclass
class StateInventoryRow:
    state_cd: str
    state_name: str
    state_type: str | None
    is_active: str | None
    district_count: int
    constituency_count: int
    sample_ac_no: str | None = None
    sample_ac_name: str | None = None
    sample_languages: dict[str, str] = field(default_factory=dict)
    language_codes: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class HierarchyInventory:
    states: list[StateInventoryRow]
    districts: list[dict[str, Any]]
    constituencies: list[dict[str, Any]]
    totals: dict[str, int]

    # Documented hierarchy (verified against public APIs + UI labels)
    hierarchy_levels: list[str] = field(
        default_factory=lambda: [
            "Country (IN, implicit)",
            "State / UT (stateCd)",
            "District (districtNo / districtCd)",
            "Assembly Constituency (asmblyNo / acNumber)",
            "Year / Revision type (via signed get-publish-eroll-type)",
            "Language (lang codes from get-ac-languages)",
            "Part (polling-station part list via signed get-publish-part-list)",
            "PDF (generate-published-pdfs → object store / presigned URL)",
        ]
    )
    hierarchy_notes: list[str] = field(
        default_factory=lambda: [
            "Section appears in SIR search UIs (SELECT_SECTION_NO) but is not a required "
            "level on the primary /download-eroll PDF path observed in API surface.",
            "Parliamentary Constituency is NOT in the download-eroll cascade.",
            "Roll type / year selection sits between AC and Part.",
        ]
    )


class InventoryBuilder:
    """Build geo inventory using only public unsigned endpoints."""

    def __init__(self, settings: Settings | None = None, probe: GatewayProbe | None = None) -> None:
        self.settings = settings or get_settings()
        self.probe = probe or GatewayProbe(self.settings)

    def build(self) -> HierarchyInventory:
        states_raw = self.probe.get_states()
        state_rows: list[StateInventoryRow] = []
        all_districts: list[dict[str, Any]] = []
        all_acs: list[dict[str, Any]] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        ) as progress:
            task = progress.add_task("Inventorying states", total=len(states_raw))
            for st in states_raw:
                cd = st["stateCd"]
                name = st.get("stateName", "")
                progress.update(task, description=f"{cd} {name}")
                dists = self.probe.get_districts(cd)
                acs = self.probe.get_constituencies(cd)
                for d in dists:
                    row = dict(d)
                    row["stateCd"] = cd
                    row["stateName"] = name
                    all_districts.append(row)
                for ac in acs:
                    row = dict(ac)
                    row["stateName"] = name
                    all_acs.append(row)

                langs: dict[str, str] = {}
                sample_ac_no = None
                sample_ac_name = None
                if acs and self.settings.recon.probe_languages_per_state:
                    first = acs[0]
                    sample_ac_no = str(first.get("asmblyNo", ""))
                    sample_ac_name = first.get("asmblyName")
                    if sample_ac_no:
                        langs = self.probe.get_ac_languages(cd, sample_ac_no)

                state_rows.append(
                    StateInventoryRow(
                        state_cd=cd,
                        state_name=name,
                        state_type=st.get("stateType"),
                        is_active=st.get("isActive"),
                        district_count=len(dists),
                        constituency_count=len(acs),
                        sample_ac_no=sample_ac_no,
                        sample_ac_name=sample_ac_name,
                        sample_languages=langs,
                        language_codes=list(langs.keys()),
                    )
                )
                progress.advance(task)

        totals = {
            "states": len(state_rows),
            "districts": len(all_districts),
            "constituencies": len(all_acs),
            "states_with_languages": sum(1 for s in state_rows if s.language_codes),
        }
        logger.info("Inventory totals: {}", totals)
        return HierarchyInventory(
            states=state_rows,
            districts=all_districts,
            constituencies=all_acs,
            totals=totals,
        )

    def save(self, inventory: HierarchyInventory, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "state_summary.json").write_text(
            json.dumps([asdict(s) for s in inventory.states], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (directory / "districts.json").write_text(
            json.dumps(inventory.districts, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (directory / "constituencies.json").write_text(
            json.dumps(inventory.constituencies, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (directory / "totals.json").write_text(
            json.dumps(
                {
                    "totals": inventory.totals,
                    "hierarchy_levels": inventory.hierarchy_levels,
                    "hierarchy_notes": inventory.hierarchy_notes,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
