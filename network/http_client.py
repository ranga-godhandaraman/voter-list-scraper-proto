"""Polite HTTP client wrappers for public gateway endpoints."""

from __future__ import annotations

import time
from typing import Any

from urllib.parse import quote, unquote, urlparse

import httpx
import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from utils.config import Settings, get_settings


class RateLimitedSession:
    """Synchronous HTTP session with polite inter-request delay."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        proxy: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(self.default_headers())
        self._proxy = proxy
        if proxy:
            self.set_proxy(proxy)

    def set_proxy(self, proxy: str | None) -> None:
        """Set or clear HTTP(S) proxy for this session."""
        self._proxy = proxy
        if proxy:
            parsed = urlparse(proxy)
            scheme = parsed.scheme or "http"
            base = f"{scheme}://{parsed.hostname}:{parsed.port}"
            if parsed.username:
                user = unquote(parsed.username)
                passwd = unquote(parsed.password or "")
                auth_url = (
                    f"{scheme}://{quote(user, safe='')}:{quote(passwd, safe='')}"
                    f"@{parsed.hostname}:{parsed.port}"
                )
                self.session.proxies = {"http": auth_url, "https": auth_url}
            else:
                self.session.proxies = {"http": base, "https": base}
        else:
            self.session.proxies = {}

    def default_headers(self) -> dict[str, str]:
        t = self.settings.target
        h = self.settings.http
        return {
            "User-Agent": h.user_agent,
            "Accept": "application/json, text/html, */*",
            "applicationName": t.application_name,
            "PLATFORM-TYPE": t.platform_type,
            "channelidobo": t.channel_id,
        }

    def _throttle(self) -> None:
        delay = self.settings.http.request_delay_seconds
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < delay:
            time.sleep(delay - elapsed)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=1, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
    )
    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        allow_redirects: bool = True,
    ) -> requests.Response:
        self._throttle()
        merged = dict(self.session.headers)
        if headers:
            merged.update(headers)
        timeout = timeout or self.settings.http.timeout_seconds
        logger.debug("{} {}", method.upper(), url)
        resp = self.session.request(
            method=method.upper(),
            url=url,
            json=json_body,
            headers=merged,
            timeout=timeout,
            allow_redirects=allow_redirects,
            verify=self.settings.http.verify_ssl,
        )
        self._last_request_at = time.monotonic()
        return resp

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, json_body: Any | None = None, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, json_body=json_body, **kwargs)


class AsyncHttpClient:
    """Async httpx client for optional public probes (still rate-limited by caller)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        t = self.settings.target
        h = self.settings.http
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": h.user_agent,
                "Accept": "application/json, text/html, */*",
                "applicationName": t.application_name,
                "PLATFORM-TYPE": t.platform_type,
                "channelidobo": t.channel_id,
            },
            timeout=h.timeout_seconds,
            verify=h.verify_ssl,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def get(self, url: str) -> httpx.Response:
        return await self.client.get(url)
