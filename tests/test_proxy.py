"""Tests for proxy list parsing."""

from __future__ import annotations

from pathlib import Path

from downloader.proxy import (
    ProxyPool,
    load_proxies_from_file,
    mask_proxy,
    normalize_proxy_url,
)


def test_normalize_host_port() -> None:
    assert normalize_proxy_url("1.2.3.4:8080") == "http://1.2.3.4:8080"


def test_normalize_user_pass_at() -> None:
    assert (
        normalize_proxy_url("http://user:secret@5.6.7.8:3128")
        == "http://user:secret@5.6.7.8:3128"
    )


def test_normalize_host_port_user_pass() -> None:
    url = normalize_proxy_url("5.6.7.8:3128:myuser:mypass")
    assert url == "http://myuser:mypass@5.6.7.8:3128"


def test_normalize_host_port_user_pass_exit_ip() -> None:
    """Provider format: host:port:user:pass:exit_ip (5th field ignored)."""
    url = normalize_proxy_url("45.39.20.57:5486:prtajuwh:secretpass:104.252.107.4")
    assert url == "http://prtajuwh:secretpass@45.39.20.57:5486"


def test_mask_proxy() -> None:
    assert "***" in mask_proxy("http://user:pass@1.2.3.4:8080")


def test_load_file(tmp_path: Path) -> None:
    p = tmp_path / "proxies.txt"
    p.write_text(
        "# comment\n"
        "1.1.1.1:8000\n"
        "user:pass@2.2.2.2:9000\n"
        "3.3.3.3:7000:u:p\n",
        encoding="utf-8",
    )
    urls = load_proxies_from_file(p)
    assert len(urls) == 3
    assert urls[0] == "http://1.1.1.1:8000"


def test_proxy_pool_rotate() -> None:
    pool = ProxyPool(["http://1.1.1.1:1", "http://2.2.2.2:2"])
    assert pool.current == "http://1.1.1.1:1"
    assert pool.rotate() == "http://2.2.2.2:2"
    assert pool.rotate() == "http://1.1.1.1:1"
