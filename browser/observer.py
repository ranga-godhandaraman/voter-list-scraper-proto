"""Observational browser reconnaissance using Playwright.

Does NOT automate CAPTCHA solving, mass downloads, or protection bypass.
Captures DOM structure, network traffic, cookies, and storage as a real browser would.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from utils.config import Settings, get_settings


@dataclass
class DomElementInfo:
    tag: str
    element_id: str | None
    classes: list[str]
    name: str | None
    role: str | None
    text_preview: str
    selector_hint: str


@dataclass
class BrowserReconResult:
    url: str
    final_url: str
    title: str
    framework_signals: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)
    session_storage: dict[str, str] = field(default_factory=dict)
    network_requests: list[dict[str, Any]] = field(default_factory=list)
    dom_elements: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BrowserObserver:
    """Load the SPA and capture publicly visible structure + network."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def observe_download_eroll(self) -> BrowserReconResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is required for browser observation. "
                "Install with: pip install playwright && playwright install chromium"
            ) from exc

        url = self.settings.target.download_eroll_url
        result = BrowserReconResult(url=url, final_url=url, title="")
        network: list[dict[str, Any]] = []

        logger.info("Observing SPA at {}", url)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.settings.browser.headless)
            context = browser.new_context(
                user_agent=self.settings.http.user_agent,
                ignore_https_errors=False,
            )
            page = context.new_page()
            page.set_default_timeout(self.settings.browser.navigation_timeout_ms)

            def on_request(req: Any) -> None:
                network.append(
                    {
                        "phase": "request",
                        "method": req.method,
                        "url": req.url,
                        "resource_type": req.resource_type,
                        "headers": dict(req.headers),
                    }
                )

            def on_response(resp: Any) -> None:
                network.append(
                    {
                        "phase": "response",
                        "method": resp.request.method,
                        "url": resp.url,
                        "status": resp.status,
                        "headers": dict(resp.headers),
                        "resource_type": resp.request.resource_type,
                    }
                )

            if self.settings.browser.capture_network:
                page.on("request", on_request)
                page.on("response", on_response)

            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(self.settings.browser.max_wait_for_spa_ms)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"navigation: {exc}")
                logger.warning("Navigation issue: {}", exc)

            result.final_url = page.url
            result.title = page.title()
            result.network_requests = network

            # Framework / asset signals from DOM
            result.scripts = page.eval_on_selector_all(
                "script[src]", "els => els.map(e => e.src)"
            )
            result.stylesheets = page.eval_on_selector_all(
                "link[rel='stylesheet']", "els => els.map(e => e.href)"
            )
            result.framework_signals = self._detect_framework(result.scripts, page.content())

            # Interactive elements after SPA hydrate
            result.dom_elements = page.evaluate(
                """() => {
                  const nodes = Array.from(document.querySelectorAll(
                    'select, input, button, a, [role="combobox"], [role="listbox"], label, h1, h2, h3'
                  ));
                  return nodes.slice(0, 250).map((el, idx) => {
                    const text = (el.innerText || el.textContent || '').trim().slice(0, 120);
                    const id = el.id || null;
                    const classes = el.className && typeof el.className === 'string'
                      ? el.className.split(/\\s+/).filter(Boolean).slice(0, 8) : [];
                    const tag = el.tagName.toLowerCase();
                    let selector = tag;
                    if (id) selector = `#${id}`;
                    else if (classes.length) selector = `${tag}.${classes[0]}`;
                    return {
                      tag, element_id: id, classes, name: el.getAttribute('name'),
                      role: el.getAttribute('role'), text_preview: text, selector_hint: selector,
                      index: idx
                    };
                  });
                }"""
            )

            result.meta = page.evaluate(
                """() => {
                  const metas = {};
                  document.querySelectorAll('meta').forEach(m => {
                    const k = m.getAttribute('name') || m.getAttribute('property');
                    if (k) metas[k] = m.getAttribute('content');
                  });
                  return {
                    metas,
                    root_html: document.documentElement.outerHTML.slice(0, 2000),
                    has_root: !!document.getElementById('root'),
                    body_text_preview: (document.body && document.body.innerText || '').slice(0, 1500)
                  };
                }"""
            )

            if self.settings.browser.capture_storage:
                result.cookies = [
                    {
                        "name": c.get("name"),
                        "domain": c.get("domain"),
                        "path": c.get("path"),
                        "httpOnly": c.get("httpOnly"),
                        "secure": c.get("secure"),
                        "sameSite": c.get("sameSite"),
                        "expires": c.get("expires"),
                    }
                    for c in context.cookies()
                ]
                try:
                    result.local_storage = page.evaluate(
                        "() => Object.fromEntries(Object.entries(localStorage))"
                    )
                    result.session_storage = page.evaluate(
                        "() => Object.fromEntries(Object.entries(sessionStorage))"
                    )
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"storage: {exc}")

            browser.close()

        logger.info(
            "Browser observation complete: {} network events, {} DOM nodes",
            len(result.network_requests),
            len(result.dom_elements),
        )
        return result

    @staticmethod
    def _detect_framework(scripts: list[str], html: str) -> list[str]:
        signals: list[str] = []
        blob = " ".join(scripts) + " " + html[:5000]
        checks = {
            "React (#root + /static/js/main.*)": "id=\"root\"" in html or "/static/js/main." in blob,
            "Create React App / Webpack hashed bundles": "/static/js/" in blob and ".chunk.js" in blob,
            "Redux Toolkit Query (RTK Query)": "contentLoaderServiceApi" in html,  # rare in HTML
            "Angular legacy scripts present": "/angular/" in blob,
            "Bootstrap CSS": "bootstrap" in blob.lower(),
            "jQuery (transliteration package)": "jquery" in blob.lower(),
            "Akamai Boomerang (RUM)": "go-mpulse.net" in blob or "BOOMR" in html,
        }
        for label, ok in checks.items():
            if ok:
                signals.append(label)
        # Always note React SPA from known architecture
        if "React" not in " ".join(signals):
            signals.append("React SPA (Citizen Service Portal shell)")
        return signals

    def save(self, result: BrowserReconResult, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False), encoding="utf-8")
        return path
