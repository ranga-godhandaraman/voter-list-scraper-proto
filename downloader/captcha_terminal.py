"""Terminal CAPTCHA flow — user never interacts with the browser."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from loguru import logger
from rich.console import Console

from network.http_client import RateLimitedSession

console = Console()
CAPTCHA_URL = "https://gateway-voters.eci.gov.in/api/v1/captcha-service/getCaptcha/EROLL"


def fetch_captcha_image(session: RateLimitedSession, dest: Path) -> Path:
    """Download the current EROLL captcha image to ``dest``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = session.get(CAPTCHA_URL)
    resp.raise_for_status()
    content_type = (resp.headers.get("content-type") or "").lower()
    if "json" in content_type:
        data = resp.json()
        raw = data.get("captcha") or data.get("data") or data.get("image") or ""
        if isinstance(raw, str) and raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        img_bytes = base64.b64decode(raw)
        dest.write_bytes(img_bytes)
    else:
        dest.write_bytes(resp.content)
    logger.debug("Captcha image saved to {}", dest)
    return dest


def prompt_captcha_terminal(image_path: Path, *, label: str = "") -> str:
    """Show captcha path and read the answer from the terminal."""
    console.print()
    if label:
        console.print(f"[cyan]{label}[/cyan]")
    console.print(
        f"[bold]Open the captcha image:[/bold] [underline]{image_path.resolve()}[/underline]"
    )
    console.print(
        "[dim]Type the characters exactly as shown (ignore spaces). "
        "Press Enter here — not in the browser.[/dim]"
    )
    while True:
        answer = input("Captcha: ").strip()
        cleaned = re.sub(r"\s+", "", answer)
        if len(cleaned) >= 4:
            return cleaned
        console.print("[yellow]Captcha looks too short — try again.[/yellow]")


def fill_captcha_in_page(page, captcha_text: str) -> None:
    """Inject captcha into the SPA form field."""
    page.evaluate(
        """(value) => {
          const el = document.querySelector('input[name=captcha]');
          if (!el) throw new Error('captcha input not found');
          el.focus();
          el.value = value;
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        captcha_text,
    )
