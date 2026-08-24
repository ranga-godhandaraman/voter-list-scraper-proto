"""Gateway API inventory and public endpoint probing."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from loguru import logger

from network import RateLimitedSession
from utils.config import Settings, get_settings


@dataclass
class EndpointFinding:
    """Documented API endpoint observation."""

    method: str
    path: str
    full_url: str
    category: str
    auth_required: str  # none | bearer | signed_headers | unknown
    status_observed: int | None = None
    content_type: str | None = None
    notes: str = ""
    sample_params: dict[str, Any] = field(default_factory=dict)
    sample_response_keys: list[str] = field(default_factory=list)
    response_bytes: int | None = None


@dataclass
class NetworkCallRecord:
    """Single HTTP call metadata for reporting."""

    timestamp: str
    method: str
    url: str
    status: int
    elapsed_ms: float
    request_headers: dict[str, str]
    response_headers: dict[str, str]
    body_preview: str = ""
    error: str | None = None


# Endpoints discovered from public JS bundles / live probes.
# Signed/encrypted PDF endpoints are listed for documentation only.
KNOWN_ENDPOINTS: list[dict[str, Any]] = [
    {
        "method": "GET",
        "path": "/api/v1/common/states",
        "category": "geo",
        "auth_required": "none",
        "notes": "Public list of States/UTs",
    },
    {
        "method": "GET",
        "path": "/api/v1/common/districts/{stateCd}",
        "category": "geo",
        "auth_required": "none",
        "notes": "Public districts for a state code (e.g. S24)",
    },
    {
        "method": "GET",
        "path": "/api/v1/common/constituencies?stateCode={stateCd}",
        "category": "geo",
        "auth_required": "none",
        "notes": "Public assembly constituencies; fields include asmblyNo, districtCd",
    },
    {
        "method": "GET",
        "path": "/api/v1/common/acs/{stateCd}",
        "category": "geo",
        "auth_required": "none",
        "notes": "Alternate AC path; may return empty array depending on state",
    },
    {
        "method": "POST",
        "path": "/api/v1/printing-publish/get-ac-languages",
        "category": "eroll",
        "auth_required": "none",
        "notes": "Body: {stateCd, acNumber}. Returns language map e.g. {HIN:HINDI}",
        "sample_params": {"stateCd": "S24", "acNumber": "87"},
    },
    {
        "method": "GET",
        "path": "/api/v1/printing-publish/get-publish-eroll-type",
        "category": "eroll",
        "auth_required": "signed_headers",
        "notes": (
            "Requires query params stateCd, year, misKey AND client-generated headers "
            "accept_yek / accept_rotcev (request signing). Not probed beyond identifying requirement."
        ),
        "sample_params": {"stateCd": "<signed>", "year": "<signed>", "misKey": "<signed>"},
    },
    {
        "method": "POST",
        "path": "/api/v1/printing-publish/get-publish-part-list",
        "category": "eroll",
        "auth_required": "signed_headers",
        "notes": (
            "Returns part list for selected AC/year/language/roll type. "
            "Likely goes through encrypting RTK baseQuery; empty HTTP 400 without signing."
        ),
    },
    {
        "method": "POST",
        "path": "/api/v1/printing-publish/generate-published-pdfs",
        "category": "eroll",
        "auth_required": "signed_headers",
        "notes": "Triggers PDF generation / returns object-store reference or presigned URL.",
    },
    {
        "method": "POST",
        "path": "/api/v1/printing-publish/download-statutory-report",
        "category": "eroll",
        "auth_required": "signed_headers",
        "notes": "Statutory report download (related UI route /download-statutory-report).",
    },
    {
        "method": "GET",
        "path": "/api/v1/document-adhoc/getPresignedFile",
        "category": "storage",
        "auth_required": "bearer",
        "notes": "Presigned object-storage URL; query: bucketName, fileName",
    },
    {
        "method": "GET",
        "path": "/api/v1/document-adhoc/downloadPresignedFile",
        "category": "storage",
        "auth_required": "unknown",
        "notes": "Client uses returned preSignedUrl for browser download.",
    },
    {
        "method": "GET",
        "path": "/api/v1/captcha-service/getCaptcha/{id}",
        "category": "security",
        "auth_required": "none",
        "notes": "Returns captcha image/data payload for citizen flows (not always on download-eroll).",
    },
    {
        "method": "GET",
        "path": "/api/v1/captcha-service/generateVoiceCaptcha/{id}",
        "category": "security",
        "auth_required": "none",
        "notes": "Voice captcha asset URL pattern from SPA.",
    },
    {
        "method": "POST",
        "path": "/api/v1/captcha-service/verifyCaptcha/",
        "category": "security",
        "auth_required": "none",
        "notes": "Captcha verification endpoint (identify only).",
    },
    {
        "method": "GET",
        "path": "/api/v1/common/part/get/bystatecd/districtcd/acNumber",
        "category": "geo",
        "auth_required": "bearer",
        "notes": "Part master data; observed 401 without bearer token.",
    },
    {
        "method": "GET",
        "path": "/api/v1/citizen/sir/getDistrict",
        "category": "sir",
        "auth_required": "unknown",
        "notes": "SIR-specific district listing; requires state header in SPA.",
    },
    {
        "method": "GET",
        "path": "/api/v1/citizen/sir/getAsmblyByDist",
        "category": "sir",
        "auth_required": "unknown",
        "notes": "SIR assembly-by-district.",
    },
    {
        "method": "GET",
        "path": "/api/v1/citizen/sir/getPartByAc",
        "category": "sir",
        "auth_required": "unknown",
        "notes": "SIR parts by assembly.",
    },
    {
        "method": "POST",
        "path": "/api/v1/elastic-sir-citizen/get-eroll-data-2003-by-epic-captcha",
        "category": "sir_search",
        "auth_required": "captcha",
        "notes": "Historical SIR eroll search by EPIC + captcha.",
    },
]


class GatewayProbe:
    """Probe public gateway endpoints and record findings."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        proxy: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.http = RateLimitedSession(self.settings, proxy=proxy)
        self.calls: list[NetworkCallRecord] = []
        self.findings: list[EndpointFinding] = []

    def set_proxy(self, proxy: str | None) -> None:
        self.http.set_proxy(proxy)

    def _record(
        self,
        method: str,
        url: str,
        resp: Any | None,
        elapsed_ms: float,
        error: str | None = None,
        body_preview: str = "",
    ) -> None:
        req_headers = {k: str(v) for k, v in self.http.default_headers().items()}
        resp_headers: dict[str, str] = {}
        status = 0
        if resp is not None:
            status = int(resp.status_code)
            resp_headers = {k: str(v) for k, v in resp.headers.items()}
            if not body_preview:
                try:
                    body_preview = (resp.text or "")[:400]
                except Exception:
                    body_preview = ""
        self.calls.append(
            NetworkCallRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                method=method,
                url=url,
                status=status,
                elapsed_ms=elapsed_ms,
                request_headers=req_headers,
                response_headers=resp_headers,
                body_preview=body_preview,
                error=error,
            )
        )

    def gateway(self, path: str) -> str:
        return urljoin(self.settings.target.gateway_url.rstrip("/") + "/", path.lstrip("/"))

    def probe_known_catalog(self) -> list[EndpointFinding]:
        """Materialize catalog entries (documentation + selective live checks)."""
        base = self.settings.target.gateway_url.rstrip("/")
        findings: list[EndpointFinding] = []
        for item in KNOWN_ENDPOINTS:
            findings.append(
                EndpointFinding(
                    method=item["method"],
                    path=item["path"],
                    full_url=f"{base}{item['path']}",
                    category=item["category"],
                    auth_required=item["auth_required"],
                    notes=item.get("notes", ""),
                    sample_params=item.get("sample_params", {}),
                )
            )
        self.findings = findings
        return findings

    def get_states(self) -> list[dict[str, Any]]:
        url = self.gateway("/api/v1/common/states")
        t0 = datetime.now(timezone.utc)
        resp = self.http.get(url)
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
        self._record("GET", url, resp, elapsed)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected states payload")
        logger.info("Fetched {} states/UTs", len(data))
        return data

    def get_districts(self, state_cd: str) -> list[dict[str, Any]]:
        url = self.gateway(f"/api/v1/common/districts/{state_cd}")
        t0 = datetime.now(timezone.utc)
        resp = self.http.get(url)
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
        self._record("GET", url, resp, elapsed)
        if resp.status_code != 200:
            logger.warning("Districts {} -> {}", state_cd, resp.status_code)
            return []
        data = resp.json()
        return data if isinstance(data, list) else []

    def get_constituencies(self, state_cd: str) -> list[dict[str, Any]]:
        url = self.gateway(f"/api/v1/common/constituencies?stateCode={state_cd}")
        t0 = datetime.now(timezone.utc)
        resp = self.http.get(url)
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
        self._record("GET", url, resp, elapsed)
        if resp.status_code != 200:
            logger.warning("Constituencies {} -> {}", state_cd, resp.status_code)
            return []
        data = resp.json()
        return data if isinstance(data, list) else []

    def get_ac_languages(self, state_cd: str, ac_number: str | int) -> dict[str, str]:
        url = self.gateway("/api/v1/printing-publish/get-ac-languages")
        body = {"stateCd": state_cd, "acNumber": str(ac_number)}
        t0 = datetime.now(timezone.utc)
        resp = self.http.post(url, json_body=body)
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
        self._record("POST", url, resp, elapsed)
        if resp.status_code != 200:
            return {}
        payload = resp.json()
        langs = payload.get("payload") if isinstance(payload, dict) else None
        return langs if isinstance(langs, dict) else {}

    def probe_signed_endpoint_requirement(self) -> dict[str, Any]:
        """Confirm signed endpoint rejects unsigned calls (identify only)."""
        if self.settings.recon.skip_signed_endpoints:
            url = self.gateway(
                "/api/v1/printing-publish/get-publish-eroll-type?stateCd=S24&year=2025&misKey=EROLL"
            )
            t0 = datetime.now(timezone.utc)
            resp = self.http.get(url)
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
            self._record("GET", url, resp, elapsed)
            return {
                "endpoint": url,
                "status": resp.status_code,
                "body": (resp.text or "")[:500],
                "conclusion": (
                    "Unsigned call rejected/failed as expected. "
                    "Client-side request signing required; not reversed."
                ),
            }
        return {"skipped": True}

    def save_raw(self, name: str, data: Any) -> Path:
        path = self.settings.raw_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return path

    def export_calls(self) -> list[dict[str, Any]]:
        return [asdict(c) for c in self.calls]

    def export_findings(self) -> list[dict[str, Any]]:
        return [asdict(f) for f in self.findings]
