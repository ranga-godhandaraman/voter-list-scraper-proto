"""CLI for the electoral-roll downloader."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from downloader.downloader import ErollDownloader
from downloader.models import DownloaderConfig
from downloader.state_mapping import list_short_codes, resolve_state
from utils.logging import setup_logging

app = typer.Typer(
    name="download-eroll",
    help=(
        "Download electoral-roll PDFs for a district. "
        "One captcha per parts-table page (~10 parts), batched per assembly."
    ),
    add_completion=False,
)
console = Console()


def _parse_config(
    state: str,
    district: Optional[str],
    revision: str,
    language: Optional[str],
    output: Path,
    workers: int,
    delay: float,
    resume: bool,
    force: bool,
    verbose: bool,
    dry_run: bool,
    summary: bool,
    headless: bool,
    captcha_timeout: int,
    roll_index: Optional[int],
    max_assemblies: Optional[int],
    proxies: Optional[Path],
) -> DownloaderConfig:
    return DownloaderConfig(
        state=state,
        district_name=district,
        revision=revision,
        language=language.upper() if language else None,
        output_dir=output,
        workers=workers,
        delay=delay,
        resume=resume,
        force=force,
        verbose=verbose,
        dry_run=dry_run,
        summary=summary,
        headless=headless,
        captcha_timeout_seconds=captcha_timeout,
        roll_index=roll_index,
        max_assemblies=max_assemblies,
        proxy_file=proxies,
    )


@app.callback(invoke_without_command=True)
def main(
    state: Optional[str] = typer.Option(
        None, "--state", "-s", help="State short code (AP, TN, GJ, …)"
    ),
    district: Optional[str] = typer.Option(
        None,
        "--district",
        "-d",
        help="District name (required for downloads). Example: Ahmedabad",
    ),
    revision: str = typer.Option(
        "auto",
        "--revision",
        "-r",
        help="Revision year or 'auto'",
    ),
    language: Optional[str] = typer.Option(
        None, "--language", "-l", help="Language code e.g. ENG, GUJ, TAM"
    ),
    output: Path = typer.Option(Path("downloads"), "--output", "-o", help="Output root"),
    workers: int = typer.Option(1, "--workers", "-w", help="Reserved (downloads are serial)"),
    delay: float = typer.Option(1.0, "--delay", help="Delay between AC batches (seconds)"),
    resume: bool = typer.Option(True, "--resume/--no-resume", help="Skip completed files"),
    force: bool = typer.Option(False, "--force", help="Redownload even if file exists"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List parts only; no PDF download"
    ),
    summary: bool = typer.Option(True, "--summary/--no-summary", help="Print summary table"),
    headless: bool = typer.Option(
        False,
        "--headless/--headed",
        help="Headless browser (dry-run only; downloads open a visible browser for captcha)",
    ),
    captcha_timeout: int = typer.Option(
        300, "--captcha-timeout", help="Seconds to wait for captcha per assembly batch"
    ),
    roll_index: Optional[int] = typer.Option(
        None,
        "--roll-index",
        help="Pick roll type by number when SIR Draft is unavailable (non-interactive)",
    ),
    max_assemblies: Optional[int] = typer.Option(
        None, "--max-assemblies", help="Limit assemblies scanned (testing)"
    ),
    proxies: Optional[Path] = typer.Option(
        None,
        "--proxies",
        help="Path to .txt file with proxy list (one per line). Omit = local IP.",
    ),
    list_states: bool = typer.Option(False, "--list-states", help="List short codes and exit"),
) -> None:
    """Download all part PDFs for one district."""
    if list_states:
        for code in list_short_codes():
            info = resolve_state(code)
            console.print(f"{code:3}  {info.eci_state_cd:4}  {info.name}")
        raise typer.Exit(0)

    if not state:
        console.print("[red]--state / -s is required (or use --list-states)[/red]")
        raise typer.Exit(2)

    try:
        resolve_state(state)
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    if not dry_run and not district:
        console.print(
            "[red]--district is required for downloads.[/red]\n"
            "Example: python download_eroll.py -s GJ --district Ahmedabad"
        )
        raise typer.Exit(2)

    if not dry_run and headless:
        console.print(
            "[yellow]Downloads need a visible browser for captcha — using headed mode.[/yellow]"
        )
        headless = False

    log_level = "DEBUG" if verbose else "INFO"
    setup_logging(Path("logs"), level=log_level)

    cfg = _parse_config(
        state=state,
        district=district,
        revision=revision,
        language=language,
        output=output,
        workers=workers,
        delay=delay,
        resume=resume,
        force=force,
        verbose=verbose,
        dry_run=dry_run,
        summary=summary,
        headless=headless,
        captcha_timeout=captcha_timeout,
        roll_index=roll_index,
        max_assemblies=max_assemblies,
        proxies=proxies,
    )

    st = resolve_state(cfg.state)
    console.print(f"[cyan]State[/cyan] {st.short_code} → {st.name} ({st.eci_state_cd})")
    mode = "dry-run (list parts)" if dry_run else "download (batch captcha per AC)"
    console.print(f"[cyan]Mode[/cyan] {mode}")
    if district:
        console.print(f"[cyan]District[/cyan] {district}")
    if proxies:
        console.print(f"[cyan]Proxies[/cyan] from {proxies}")
    elif not dry_run:
        console.print("[dim]Network: local machine IP (no --proxies file)[/dim]")
    if not dry_run:
        console.print(
            "[dim]A browser window opens. Type captcha there, then press Enter in "
            "this terminal. Each parts page (~10 rows) needs one captcha.[/dim]"
        )

    try:
        result = ErollDownloader(cfg).run()
    except (ValueError, KeyError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    except Exception as exc:
        if "wait_for_selector" in str(exc) or "Timeout" in type(exc).__name__:
            console.print(
                "[red]Could not load the ECI download page in the browser.[/red]\n"
                "Try again. If Playwright Chromium is missing:\n"
                "  python -m playwright install chromium"
            )
            raise typer.Exit(1) from exc
        raise

    if summary:
        result.print_rich()


if __name__ == "__main__":
    app()
