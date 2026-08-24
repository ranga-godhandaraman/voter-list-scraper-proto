"""Proxy list loading and rotation for HTTP + Playwright."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from loguru import logger


def _build_proxy_url(host: str, port: str, user: str | None = None, password: str | None = None) -> str:
    """Build a normalized proxy URL with URL-encoded credentials."""
    if user:
        u = quote(user, safe="")
        p = quote(password or "", safe="")
        return f"http://{u}:{p}@{host}:{port}"
    return f"http://{host}:{port}"


def normalize_proxy_url(raw: str) -> str | None:
    """Normalize a proxy line to ``http://[user:pass@]host:port``.

  Supported formats::

      host:port
      host:port:user:pass
      host:port:user:pass:exit_ip   # 5th field ignored (common provider format)
      http://user:pass@host:port
      user:pass@host:port
    """
    line = (raw or "").strip()
    if not line or line.startswith("#"):
        return None

    if "@" in line or "://" in line:
        if "://" not in line:
            line = f"http://{line}"
        parsed = urlparse(line)
        if not parsed.hostname or not parsed.port:
            return None
        user = unquote(parsed.username) if parsed.username else None
        passwd = unquote(parsed.password) if parsed.password else None
        return _build_proxy_url(parsed.hostname, str(parsed.port), user, passwd)

    parts = line.split(":")
    if len(parts) >= 5 and parts[1].isdigit():
        # host:port:user:pass:exit_ip (or extra metadata) — ignore trailing fields
        host, port, user, password = parts[0], parts[1], parts[2], parts[3]
        return _build_proxy_url(host, port, user, password)
    if len(parts) == 4 and parts[1].isdigit():
        host, port, user, password = parts
        return _build_proxy_url(host, port, user, password)
    if len(parts) == 2 and parts[1].isdigit():
        return _build_proxy_url(parts[0], parts[1])

    return None


def load_proxies_from_file(path: Path) -> list[str]:
    """Load proxy URLs from a text file (one per line)."""
    text = path.expanduser().read_text(encoding="utf-8")
    out: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        url = normalize_proxy_url(raw)
        if url:
            out.append(url)
        elif raw.strip() and not raw.strip().startswith("#"):
            logger.warning("Skipping invalid proxy line {}: {}", lineno, raw.strip())
    return out


def proxy_for_playwright(proxy_url: str) -> dict[str, str]:
    """Playwright ``proxy`` dict from a normalized URL."""
    from urllib.parse import unquote

    parsed = urlparse(proxy_url)
    scheme = parsed.scheme or "http"
    server = f"{scheme}://{parsed.hostname}:{parsed.port}"
    cfg: dict[str, str] = {"server": server}
    if parsed.username:
        cfg["username"] = unquote(parsed.username)
        if parsed.password:
            cfg["password"] = unquote(parsed.password)
    return cfg


def mask_proxy(proxy_url: str) -> str:
    """Hide credentials for logs."""
    parsed = urlparse(proxy_url)
    if parsed.username:
        host = parsed.hostname or "?"
        port = parsed.port or ""
        return f"{parsed.scheme}://***:***@{host}:{port}"
    return proxy_url


class ProxyPool:
    """Round-robin proxy rotation."""

    def __init__(self, proxies: list[str]) -> None:
        self._proxies = list(proxies)
        self._index = 0
        self.current: str | None = self._proxies[0] if self._proxies else None

    @classmethod
    def from_file(cls, path: Path | None) -> ProxyPool | None:
        if path is None:
            return None
        if not path.expanduser().is_file():
            raise FileNotFoundError(f"Proxy file not found: {path}")
        proxies = load_proxies_from_file(path)
        if not proxies:
            raise ValueError(f"No valid proxies in {path}")
        logger.info("Loaded {} proxies from {}", len(proxies), path)
        return cls(proxies)

    def __len__(self) -> int:
        return len(self._proxies)

    def rotate(self) -> str | None:
        """Advance to the next proxy and return it."""
        if not self._proxies:
            return None
        self._index = (self._index + 1) % len(self._proxies)
        self.current = self._proxies[self._index]
        logger.info("Rotated to proxy {} ({}/{})", mask_proxy(self.current), self._index + 1, len(self._proxies))
        return self.current
