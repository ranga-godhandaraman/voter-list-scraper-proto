"""Static page / asset / robots analysis parsers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

from network import RateLimitedSession
from utils.config import Settings, get_settings


@dataclass
class SiteStructureFinding:
    page_url: str
    status: int
    is_spa_shell: bool
    title: str
    scripts: list[str] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    security_headers: dict[str, str] = field(default_factory=dict)
    cookies_set: list[str] = field(default_factory=list)
    csp_connect_src: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RobotsFinding:
    url: str
    status: int
    is_html_fallback: bool
    body_preview: str
    notes: str


@dataclass
class BundleFinding:
    url: str
    size_bytes: int
    api_paths: list[str]
    routes: list[str]
    external_ceo_links: dict[str, str]
    base_urls: dict[str, str]
    security_signals: list[str]


class StaticSiteAnalyzer:
    """Analyze HTML shell, robots, manifests, and JS bundle strings."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.http = RateLimitedSession(self.settings)

    def analyze_shell(self) -> SiteStructureFinding:
        url = self.settings.target.download_eroll_url
        resp = self.http.get(url)
        html = resp.text or ""
        soup = BeautifulSoup(html, "lxml")
        scripts = [s.get("src") for s in soup.find_all("script", src=True)]
        css = [l.get("href") for l in soup.find_all("link", rel="stylesheet")]
        meta = {}
        for m in soup.find_all("meta"):
            key = m.get("name") or m.get("property")
            if key:
                meta[key] = m.get("content") or ""

        interesting = [
            "content-security-policy",
            "strict-transport-security",
            "x-frame-options",
            "x-content-type-options",
            "referrer-policy",
            "cache-control",
            "server-timing",
            "clear-site-data",
            "set-cookie",
        ]
        sec = {k: v for k, v in resp.headers.items() if k.lower() in interesting}
        csp = resp.headers.get("content-security-policy", "")
        connect = []
        m = re.search(r"connect-src([^;]+)", csp)
        if m:
            connect = [t for t in m.group(1).split() if t.startswith("http")]

        notes = []
        is_spa = bool(soup.find(id="root")) or "You need to enable JavaScript" in html
        if is_spa:
            notes.append("CSR React shell: empty #root, JS required")
        if "ak_p" in (resp.headers.get("server-timing") or ""):
            notes.append("Akamai CDN edge (server-timing ak_p)")
        if "/angular/" in html:
            notes.append("Legacy Angular script tags co-loaded with React main bundle")

        finding = SiteStructureFinding(
            page_url=url,
            status=resp.status_code,
            is_spa_shell=is_spa,
            title=(soup.title.string if soup.title else "") or "",
            scripts=[s for s in scripts if s],
            stylesheets=[c for c in css if c],
            meta=meta,
            security_headers=sec,
            cookies_set=resp.headers.get("set-cookie", "").split("\n") if resp.headers.get("set-cookie") else [],
            csp_connect_src=connect,
            notes=notes,
        )
        logger.info("Shell analysis complete status={}", finding.status)
        return finding

    def analyze_robots(self) -> RobotsFinding:
        url = urljoin(self.settings.target.site_url + "/", "robots.txt")
        resp = self.http.get(url)
        body = resp.text or ""
        is_html = body.lstrip().lower().startswith("<!doctype html") or "<html" in body[:200].lower()
        notes = (
            "robots.txt is not served as text/plain; SPA HTML fallback returned. "
            "Treat as: no crawl directives published at this path; still obey site ToS and polite limits."
            if is_html
            else "Parsed robots.txt body."
        )
        return RobotsFinding(
            url=url,
            status=resp.status_code,
            is_html_fallback=is_html,
            body_preview=body[:500],
            notes=notes,
        )

    def analyze_asset_manifest(self) -> dict[str, Any]:
        url = urljoin(self.settings.target.site_url + "/", "asset-manifest.json")
        resp = self.http.get(url)
        if resp.status_code != 200 or "json" not in (resp.headers.get("content-type") or ""):
            return {"status": resp.status_code, "error": "manifest unavailable"}
        data = resp.json()
        files = data.get("files", {})
        return {
            "status": 200,
            "file_count": len(files),
            "entrypoints": data.get("entrypoints", []),
            "main_js": files.get("main.js"),
            "main_css": files.get("main.css"),
            "chunk_js_count": sum(1 for k in files if "static/js/" in k and "chunk" in k),
        }

    def analyze_main_bundle(self, max_bytes: int = 3_000_000) -> BundleFinding:
        """Download main JS (public static asset) and extract string patterns."""
        manifest = self.analyze_asset_manifest()
        main_path = manifest.get("main_js") or "/static/js/main.c0386200.js"
        url = urljoin(self.settings.target.site_url + "/", main_path.lstrip("/"))
        resp = self.http.get(url)
        text = resp.text or ""
        if len(text) > max_bytes:
            text = text[:max_bytes]

        api_paths = sorted(set(re.findall(r"/api/v1/[A-Za-z0-9_\-./?=&]+", text)))
        routes = sorted(set(re.findall(r'path:"(/[^"]+)"', text)))
        # CEO historical SIR link map Sxx/Uxx
        ceo = dict(re.findall(r'(S\d{2}|U\d{2}):"(https://[^"]+)"', text))
        base_urls = dict(
            re.findall(
                r'([A-Z0-9_]+_BASE_URL|EROLL_ELASTIC_SEARCH_URL|ELECTORAL_SEARCH_URL):"(https://[^"]+)"',
                text,
            )
        )
        security = []
        for sig, label in [
            ("accept_yek", "Request signing header accept_yek present"),
            ("accept_rotcev", "Request signing header accept_rotcev present"),
            ("captcha-service", "Captcha service endpoints referenced"),
            ("preSignedUrl", "Presigned URL download pattern"),
            ("Authorization", "Bearer Authorization usage"),
            ("MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA", "Embedded RSA public key material"),
        ]:
            if sig in text:
                security.append(label)

        logger.info("Bundle analysis: {} API path strings, {} routes", len(api_paths), len(routes))
        return BundleFinding(
            url=url,
            size_bytes=len(resp.content or b""),
            api_paths=api_paths[:500],
            routes=routes,
            external_ceo_links=ceo,
            base_urls=base_urls,
            security_signals=security,
        )

    @staticmethod
    def to_dict(obj: Any) -> dict[str, Any]:
        return asdict(obj)
