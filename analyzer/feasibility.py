"""Technical feasibility assessment for a future *compliant* crawler."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ApproachScore:
    approach: str
    reliability: str  # High/Medium/Low
    complexity: str
    policy_fit: str
    notes: str


@dataclass
class FeasibilityReport:
    summary: str
    recommended_approach: str
    approaches: list[ApproachScore]
    complexity_overall: str
    risks: list[str]
    performance_notes: list[str]
    maintainability_notes: list[str]
    volume_estimates: dict[str, Any]
    compliant_future_design: list[str]


def estimate_volume(totals: dict[str, int]) -> dict[str, Any]:
    """Order-of-magnitude volume without downloading PDFs.

    Parts-per-AC vary widely (often ~150–300). Use conservative mid estimate.
    """
    states = totals.get("states", 36)
    districts = totals.get("districts", 0)
    acs = totals.get("constituencies", 0)
    parts_per_ac_low, parts_per_ac_mid, parts_per_ac_high = 80, 200, 350
    langs_per_ac_avg = 1.4  # many ACs monolingual; some bilingual

    pdfs_low = int(acs * parts_per_ac_low * 1.0)
    pdfs_mid = int(acs * parts_per_ac_mid * langs_per_ac_avg)
    pdfs_high = int(acs * parts_per_ac_high * 2.0)

    # Typical part PDF ~1–4 MB scanned/searchable
    mb_per_pdf = 2.5
    storage_mid_gb = round(pdfs_mid * mb_per_pdf / 1024, 1)
    # Polite: 1 PDF / 2s => mid runtime hours
    runtime_hours_mid = round(pdfs_mid * 2 / 3600, 1)

    return {
        "states": states,
        "districts": districts,
        "assembly_constituencies": acs,
        "parts_per_ac_assumed": {"low": parts_per_ac_low, "mid": parts_per_ac_mid, "high": parts_per_ac_high},
        "estimated_pdfs": {"low": pdfs_low, "mid": pdfs_mid, "high": pdfs_high},
        "estimated_storage_gb_at_2_5mb": {
            "low": round(pdfs_low * mb_per_pdf / 1024, 1),
            "mid": storage_mid_gb,
            "high": round(pdfs_high * mb_per_pdf / 1024, 1),
        },
        "estimated_runtime_hours_at_2s_polite": {
            "mid": runtime_hours_mid,
            "note": "Only if explicitly authorized; not performed by this project",
        },
    }


def build_feasibility(totals: dict[str, int]) -> FeasibilityReport:
    volume = estimate_volume(totals)
    approaches = [
        ApproachScore(
            approach="requests / httpx (pure HTTP)",
            reliability="Low–Medium",
            complexity="Medium",
            policy_fit="Good for public geo APIs only",
            notes=(
                "Excellent for states/districts/ACs/languages. Insufficient alone for PDF generation "
                "because of client request signing + possible captcha on adjacent flows."
            ),
        ),
        ApproachScore(
            approach="aiohttp high-concurrency",
            reliability="Low",
            complexity="High",
            policy_fit="Poor if aggressive",
            notes="Easy to violate polite limits; not recommended against Akamai-fronted gov portals.",
        ),
        ApproachScore(
            approach="Playwright / Selenium browser automation",
            reliability="Medium–High (human-paced)",
            complexity="High",
            policy_fit="Best for interactive compliant use",
            notes=(
                "Mirrors real user flow on /download-eroll. Still must not solve CAPTCHAs programmatically "
                "or hammer generate-published-pdfs. Suitable for supervised, low-volume retrieval with consent."
            ),
        ),
        ApproachScore(
            approach="Hybrid: HTTP for hierarchy + browser for signed PDF steps",
            reliability="Highest for compliant design",
            complexity="High",
            policy_fit="Best overall",
            notes=(
                "Use public APIs for inventory/indexing; use headed browser only when a human completes "
                "any challenge; store hierarchy metadata, not mass PDFs, unless formally authorized."
            ),
        ),
    ]
    return FeasibilityReport(
        summary=(
            "Public geographic hierarchy is crawlable via documented JSON APIs. "
            "PDF download path is gated by client-side request signing and object-store presigned URLs. "
            "A compliant future system should inventory via public APIs and treat PDF retrieval as "
            "an authorized, rate-limited, preferably human-supervised step — not a silent scraper."
        ),
        recommended_approach="Hybrid: HTTP for hierarchy + browser for signed PDF steps",
        approaches=approaches,
        complexity_overall="High (PDF path); Medium (geo inventory)",
        risks=[
            "Akamai edge may throttle or challenge anomalous clients",
            "Request signing algorithm can change without notice (bundle hash changes often)",
            "Presigned URLs expire; not permanent public links",
            "Legal/ToS risk if mass-downloading electoral rolls without permission",
            "CAPTCHA and auth flows adjacent to SIR/search features",
            "State CEO sites host some historical SIR rolls outside this portal",
        ],
        performance_notes=[
            f"Geo inventory: ~{totals.get('states', 36)} states × (districts+ACs+lang) ≈ hundreds of polite calls",
            f"Estimated mid PDF count ~{volume['estimated_pdfs']['mid']:,} (not downloaded)",
            f"Estimated mid storage ~{volume['estimated_storage_gb_at_2_5mb']['mid']} GB",
        ],
        maintainability_notes=[
            "Pin SPA bundle hash / re-run recon when main.*.js changes",
            "Keep endpoint catalog versioned in Excel/API inventory",
            "Prefer official bulk channels if ECI provides them later",
        ],
        volume_estimates=volume,
        compliant_future_design=[
            "Phase 1: nightly geo inventory via public APIs (this project)",
            "Phase 2: detect revision availability only through unsigned signals / official notices",
            "Phase 3: if authorized, human-in-the-loop browser session for sample/part downloads",
            "Phase 4: store checksums + metadata; incremental updates by revision year",
            "Never embed reversed signing keys or CAPTCHA solvers",
        ],
    )


def report_as_dict(report: FeasibilityReport) -> dict[str, Any]:
    return asdict(report)
