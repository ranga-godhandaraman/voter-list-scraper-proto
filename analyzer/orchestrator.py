"""Orchestrates full public reconnaissance run."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from analyzer.antibot import build_anti_bot_report, findings_as_dicts
from analyzer.feasibility import build_feasibility, report_as_dict
from analyzer.inventory import InventoryBuilder
from browser.observer import BrowserObserver
from network.gateway import GatewayProbe
from parser.site import StaticSiteAnalyzer
from report.docs_builder import write_docs
from report.excel_builder import build_workbook
from utils.config import Settings, ensure_output_dirs, get_settings


class ReconOrchestrator:
    """End-to-end reconnaissance pipeline (public resources only)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ensure_output_dirs(self.settings)
        self.errors: list[dict[str, str]] = []

    def run(
        self,
        *,
        skip_browser: bool = False,
        skip_inventory: bool = False,
        use_cached_inventory: Path | None = None,
    ) -> dict[str, Any]:
        logger.info("Starting ECI eroll reconnaissance")
        static = StaticSiteAnalyzer(self.settings)
        probe = GatewayProbe(self.settings)

        # 1. Shell / robots / bundle
        shell = static.analyze_shell()
        robots = static.analyze_robots()
        manifest = static.analyze_asset_manifest()
        bundle = static.analyze_main_bundle()
        probe.probe_known_catalog()
        signed = probe.probe_signed_endpoint_requirement()

        # 2. Inventory
        inventory_data: dict[str, Any]
        if use_cached_inventory and use_cached_inventory.exists():
            logger.info("Loading cached inventory from {}", use_cached_inventory)
            inventory_data = json.loads(use_cached_inventory.read_text(encoding="utf-8"))
            # Adapt cached shape if needed
            if "inventory" in inventory_data and "states" not in inventory_data:
                inventory_data = self._adapt_tmp_cache(inventory_data)
        elif skip_inventory:
            inventory_data = {
                "states": [],
                "districts": [],
                "constituencies": [],
                "totals": {"states": 0, "districts": 0, "constituencies": 0},
                "hierarchy_levels": [],
                "hierarchy_notes": [],
            }
        else:
            builder = InventoryBuilder(self.settings, probe)
            inv = builder.build()
            builder.save(inv, self.settings.raw_path / "inventory")
            inventory_data = {
                "states": [asdict(s) for s in inv.states],
                "districts": inv.districts,
                "constituencies": inv.constituencies,
                "totals": inv.totals,
                "hierarchy_levels": inv.hierarchy_levels,
                "hierarchy_notes": inv.hierarchy_notes,
            }

        # 3. Browser observation
        browser_dict: dict[str, Any] | None = None
        browser_cache = self.settings.raw_path / "browser_observation.json"
        if skip_browser and browser_cache.exists():
            logger.info("Loading cached browser observation from {}", browser_cache)
            browser_dict = json.loads(browser_cache.read_text(encoding="utf-8"))
        elif not skip_browser:
            try:
                observer = BrowserObserver(self.settings)
                bres = observer.observe_download_eroll()
                observer.save(bres, browser_cache)
                browser_dict = asdict(bres)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Browser observation failed")
                self.errors.append({"stage": "browser", "error": str(exc)})
                if browser_cache.exists():
                    browser_dict = json.loads(browser_cache.read_text(encoding="utf-8"))
        elif skip_browser:
            logger.info("Skipping browser observation")

        # 4. Anti-bot + feasibility
        antibot = build_anti_bot_report(
            robots=asdict(robots),
            shell_headers=shell.security_headers,
            bundle_security=bundle.security_signals,
            signed_probe=signed,
            browser_result=browser_dict,
        )
        feas = build_feasibility(inventory_data.get("totals") or {})

        payload = self._assemble_payload(
            shell=asdict(shell),
            robots=asdict(robots),
            manifest=manifest,
            bundle=asdict(bundle),
            inventory=inventory_data,
            signed=signed,
            antibot=findings_as_dicts(antibot),
            feasibility=report_as_dict(feas),
            browser=browser_dict,
            api_findings=probe.export_findings(),
            network_calls=probe.export_calls(),
        )

        # Persist JSON master
        master = self.settings.output_path / "recon_master.json"
        master.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

        # Excel + docs
        excel_path = self.settings.excel_path / "eci_eroll_reconnaissance.xlsx"
        build_workbook(payload, excel_path)
        write_docs(self.settings.docs_path, payload)

        logger.info("Recon complete → {}", master)
        return payload

    def _adapt_tmp_cache(self, cached: dict[str, Any]) -> dict[str, Any]:
        """Adapt inventory JSON (project or /tmp recon) into canonical shape."""
        rows = []
        # Already canonical?
        if cached.get("states") and isinstance(cached["states"], list):
            first = cached["states"][0] if cached["states"] else {}
            if "state_cd" in first:
                return cached

        for r in cached.get("inventory", []):
            rows.append(
                {
                    "state_cd": r.get("stateCd"),
                    "state_name": r.get("stateName"),
                    "state_type": r.get("stateType"),
                    "is_active": r.get("isActive"),
                    "district_count": r.get("districts"),
                    "constituency_count": r.get("constituencies"),
                    "sample_ac_name": r.get("sample_ac"),
                    "language_codes": r.get("sample_languages") or [],
                    "sample_languages": {c: c for c in (r.get("sample_languages") or [])},
                    "notes": "",
                }
            )

        districts, constituencies = self._load_sidecar_geo(rows)

        return {
            "states": rows,
            "districts": districts,
            "constituencies": constituencies,
            "totals": {
                "states": cached.get("total_states", len(rows)),
                "districts": cached.get("total_districts", len(districts)),
                "constituencies": cached.get("total_constituencies", len(constituencies)),
                "states_with_languages": sum(1 for r in rows if r["language_codes"]),
            },
            "hierarchy_levels": [
                "Country (IN)",
                "State/UT",
                "District",
                "Assembly Constituency",
                "Year/Revision",
                "Language",
                "Part",
                "PDF",
            ],
            "hierarchy_notes": [
                "Section is used in SIR search UIs, not as a required download-eroll PDF level.",
                "Parliamentary Constituency is not part of this cascade.",
            ],
        }

    def _load_sidecar_geo(self, state_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Load district/AC JSON sidecars from raw_path or /tmp/eci_recon/geo if present."""
        candidates = [
            self.settings.raw_path / "geo",
            Path("/tmp/eci_recon/geo"),
            self.settings.raw_path / "inventory",
        ]
        geo_dir = next((p for p in candidates if p.exists()), None)
        if geo_dir is None:
            return [], []

        districts: list[dict[str, Any]] = []
        constituencies: list[dict[str, Any]] = []
        for s in state_rows:
            cd = s.get("state_cd")
            name = s.get("state_name")
            if not cd:
                continue
            dfile = geo_dir / f"dist_{cd}.json"
            afile = geo_dir / f"ac_{cd}.json"
            if dfile.exists():
                try:
                    for d in json.loads(dfile.read_text(encoding="utf-8")):
                        if isinstance(d, dict):
                            d = dict(d)
                            d["stateCd"] = d.get("stateCd") or d.get("state") or cd
                            d["stateName"] = name
                            districts.append(d)
                except Exception as exc:  # noqa: BLE001
                    self.errors.append({"stage": "cache_districts", "error": f"{cd}: {exc}"})
            if afile.exists():
                try:
                    for a in json.loads(afile.read_text(encoding="utf-8")):
                        if isinstance(a, dict):
                            a = dict(a)
                            a["stateName"] = name
                            constituencies.append(a)
                except Exception as exc:  # noqa: BLE001
                    self.errors.append({"stage": "cache_acs", "error": f"{cd}: {exc}"})
        return districts, constituencies

    def _assemble_payload(self, **parts: Any) -> dict[str, Any]:
        inventory = parts["inventory"]
        shell = parts["shell"]
        bundle = parts["bundle"]
        feas = parts["feasibility"]
        browser = parts.get("browser") or {}
        signed = parts["signed"]

        download_flow = {
            "1": "Load CSR SPA at /download-eroll (Akamai → React #root hydrates)",
            "2": "Initial form fields visible: State*, Year Of Revision* (2026/2025/2024), Captcha*, Download Selected PDFs",
            "3": "Anonymous GET /api/v1/captcha-service/getCaptcha/EROLL (captcha image/data for download page)",
            "4": "GET /api/v1/common/states populates State dropdown",
            "5": "User selects State → subsequent District / AC / roll-type / language / part selectors load dynamically",
            "6": "GET /api/v1/common/districts/{stateCd} and GET /api/v1/common/constituencies?stateCode=",
            "7": "POST /api/v1/printing-publish/get-ac-languages {stateCd, acNumber}",
            "8": "SIGNED GET get-publish-eroll-type (accept_yek / accept_rotcev) for revision types",
            "9": "SIGNED POST get-publish-part-list → Part checkboxes/list",
            "10": "User solves Captcha (human) + selects parts → SIGNED POST generate-published-pdfs",
            "11": "Resolve object-store file via document-adhoc presigned URL APIs",
            "12": "Browser downloads PDF from temporary preSignedUrl",
        }

        overview = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "target": self.settings.target.download_eroll_url,
            "gateway": self.settings.target.gateway_url,
            "states": inventory.get("totals", {}).get("states"),
            "districts": inventory.get("totals", {}).get("districts"),
            "constituencies": inventory.get("totals", {}).get("constituencies"),
            "main_bundle": bundle.get("url"),
            "main_bundle_bytes": bundle.get("size_bytes"),
            "spa": shell.get("is_spa_shell"),
            "robots_is_html_fallback": parts["robots"].get("is_html_fallback"),
            "signed_endpoint_status": signed.get("status"),
            "browser_network_events": len(browser.get("network_requests") or []),
            "compliance": "public recon only; no mass PDF download; no protection bypass",
        }

        parameters = [
            {"name": "stateCd", "where": "path/query/body", "example": "S24", "required_for": "districts, languages, rolls"},
            {"name": "stateCode", "where": "query", "example": "S24", "required_for": "constituencies"},
            {"name": "acNumber", "where": "JSON body", "example": "87", "required_for": "get-ac-languages"},
            {"name": "asmblyNo", "where": "AC JSON field", "example": "87", "required_for": "maps to acNumber"},
            {"name": "districtCd", "where": "AC JSON", "example": "S2408", "required_for": "hierarchy join"},
            {"name": "year", "where": "signed query", "example": "2025", "required_for": "get-publish-eroll-type"},
            {"name": "misKey", "where": "signed query", "example": "EROLL", "required_for": "get-publish-eroll-type"},
            {"name": "accept_yek", "where": "request header", "example": "(client-generated)", "required_for": "signed printing-publish"},
            {"name": "accept_rotcev", "where": "request header", "example": "(client-generated)", "required_for": "signed printing-publish"},
            {"name": "applicationName", "where": "header", "example": "VSP", "required_for": "most gateway calls"},
            {"name": "PLATFORM-TYPE", "where": "header", "example": "web", "required_for": "SPA parity"},
            {"name": "bucketName", "where": "query", "example": "objectstorage", "required_for": "document APIs"},
            {"name": "fileName", "where": "query", "example": "(object key)", "required_for": "presign/download"},
        ]

        pdf_availability = []
        for s in inventory.get("states", []):
            pdf_availability.append(
                {
                    "state_cd": s.get("state_cd"),
                    "state_name": s.get("state_name"),
                    "geo_apis_ok": (s.get("district_count") or 0) > 0,
                    "sample_languages": ",".join(s.get("language_codes") or []),
                    "pdf_mass_checked": False,
                    "pdf_note": (
                        "Language endpoint reachable for sample AC. "
                        "Revision/PDF listing requires signed APIs — not mass-probed."
                    ),
                    "sir_external_ceo_link": (bundle.get("external_ceo_links") or {}).get(s.get("state_cd")),
                }
            )

        revision_details = [
            {
                "source": "SPA route",
                "item": "/download-eroll",
                "meaning": "Published electoral roll download UI",
            },
            {
                "source": "SPA route",
                "item": "/download-final-roll",
                "meaning": "SIR Final Roll download UI",
            },
            {
                "source": "SPA route",
                "item": "/download-sir-draft-roll",
                "meaning": "SIR Draft Roll download UI",
            },
            {
                "source": "API",
                "item": "get-publish-eroll-type",
                "meaning": "Returns available year/type for state (signed)",
            },
            {
                "source": "UI copy",
                "item": "SIR Final Roll 2025/2026 strings",
                "meaning": "Portal advertises SIR final/draft rolls for participating states",
            },
        ]

        headers_rows = [
            {"context": "site HTML", "header": k, "value": str(v)[:300]}
            for k, v in (shell.get("security_headers") or {}).items()
        ]

        technical_findings = [
            {"area": "Architecture", "finding": "React CSR SPA behind Akamai; gateway JSON APIs"},
            {"area": "Auth", "finding": "Public geo + languages; signed printing-publish; bearer elsewhere"},
            {"area": "CAPTCHA", "finding": "Download page loads /api/v1/captcha-service/getCaptcha/EROLL; Captcha* required before download"},
            {"area": "Initial DOM", "finding": "stateCode, revyear (2026/2025/2024), captcha input, Download Selected PDFs"},
            {"area": "PDF", "finding": "Generated then served via temporary preSignedUrl"},
            {"area": "robots.txt", "finding": parts["robots"].get("notes")},
            {"area": "Hierarchy", "finding": " → ".join(inventory.get("hierarchy_levels") or [])},
            {"area": "Storage", "finding": "redux-persist localStorage key persist:root; sessionStorage empty on cold load"},
        ]

        recommendations = [
            {"priority": "P0", "recommendation": "Keep using public APIs for geo inventory only"},
            {"priority": "P0", "recommendation": "Do not reverse request signing or automate CAPTCHA"},
            {"priority": "P1", "recommendation": "Re-run recon when main.*.js hash changes"},
            {"priority": "P1", "recommendation": "Seek written authorization before any bulk PDF collection"},
            {"priority": "P2", "recommendation": "Track per-state CEO historical SIR URLs separately"},
            {"priority": "P2", "recommendation": "Prefer hybrid HTTP+headed-browser design if ever authorized"},
        ]

        risks = [{"risk": r, "severity": "High"} for r in feas.get("risks", [])]

        cookies = browser.get("cookies") or []
        if not cookies:
            cookies = [{"name": "(see Set-Cookie on responses)", "note": "HttpOnly Secure SameSite=strict"}]

        dom = browser.get("dom_elements") or []
        network_browser = [
            {
                "source": "browser",
                "method": n.get("method"),
                "url": n.get("url"),
                "status": n.get("status"),
                "phase": n.get("phase"),
                "resource_type": n.get("resource_type"),
            }
            for n in (browser.get("network_requests") or [])
            if n.get("phase") == "response" and ("gateway" in (n.get("url") or "") or "api/v1" in (n.get("url") or ""))
        ][:500]

        network_calls = parts.get("network_calls") or []
        # Flatten for excel
        network_flat = [
            {
                "source": "probe",
                "timestamp": c.get("timestamp"),
                "method": c.get("method"),
                "url": c.get("url"),
                "status": c.get("status"),
                "elapsed_ms": c.get("elapsed_ms"),
                "body_preview": (c.get("body_preview") or "")[:200],
            }
            for c in network_calls
        ] + network_browser

        website_structure = {
            "title": shell.get("title"),
            "is_spa_shell": shell.get("is_spa_shell"),
            "scripts": ", ".join((shell.get("scripts") or [])[:12]),
            "framework_signals": ", ".join((browser.get("framework_signals") or bundle.get("security_signals") or [])[:12]),
            "asset_manifest_files": parts["manifest"].get("file_count"),
            "chunk_js_count": parts["manifest"].get("chunk_js_count"),
            "csp_connect_src": shell.get("csp_connect_src") or [],
            "routes_discovered": len(bundle.get("routes") or []),
            "api_paths_in_bundle": len(bundle.get("api_paths") or []),
            "notes": "; ".join(shell.get("notes") or []),
        }

        feasibility_flat = {
            "summary": feas.get("summary"),
            "recommended_approach": feas.get("recommended_approach"),
            "complexity_overall": feas.get("complexity_overall"),
            "estimated_pdfs_mid": (feas.get("volume_estimates") or {}).get("estimated_pdfs", {}).get("mid"),
            "estimated_storage_gb_mid": (feas.get("volume_estimates") or {})
            .get("estimated_storage_gb_at_2_5mb", {})
            .get("mid"),
        }

        return {
            "overview": overview,
            "states": inventory.get("states") or [],
            "districts": [
                {
                    "stateCd": d.get("stateCd") or d.get("state"),
                    "stateName": d.get("stateName"),
                    "districtNo": d.get("districtNo"),
                    "districtValue": d.get("districtValue"),
                    "districtValueHindi": d.get("districtValueHindi"),
                    "isActive": d.get("isActive"),
                }
                for d in (inventory.get("districts") or [])
            ],
            "constituencies": [
                {
                    "stateCd": a.get("stateCd"),
                    "stateName": a.get("stateName"),
                    "districtCd": a.get("districtCd"),
                    "asmblyNo": a.get("asmblyNo"),
                    "asmblyName": a.get("asmblyName"),
                    "asmblyNameL1": a.get("asmblyNameL1"),
                    "category": a.get("category"),
                }
                for a in (inventory.get("constituencies") or [])
            ],
            "revision_details": revision_details,
            "pdf_availability": pdf_availability,
            "api_endpoints": parts.get("api_findings") or [],
            "dom_elements": dom[:500],
            "network_calls": network_flat,
            "cookies": cookies,
            "headers": headers_rows,
            "parameters": parameters,
            "download_flow": download_flow,
            "website_structure": website_structure,
            "technical_findings": technical_findings,
            "feasibility": feas,
            "feasibility_flat": feasibility_flat,
            "errors": self.errors + [{"stage": "signed_probe", "error": str(signed)}],
            "recommendations": recommendations,
            "risks": risks,
            "antibot": parts["antibot"],
            "bundle_routes": bundle.get("routes"),
            "ceo_links": bundle.get("external_ceo_links"),
            "hierarchy_notes": inventory.get("hierarchy_notes"),
        }
