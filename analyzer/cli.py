"""CLI entrypoint for ECI eroll reconnaissance."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from analyzer.orchestrator import ReconOrchestrator
from utils.config import ensure_output_dirs, get_settings
from utils.logging import setup_logging

app = typer.Typer(
    name="eci-recon",
    help="Public technical reconnaissance for voters.eci.gov.in/download-eroll (no mass scraping).",
    add_completion=False,
)
console = Console()


@app.command("run")
def run_recon(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to settings.yaml"),
    skip_browser: bool = typer.Option(False, help="Skip Playwright observation"),
    skip_inventory: bool = typer.Option(False, help="Skip live geo inventory"),
    use_cached_inventory: Optional[Path] = typer.Option(
        None, help="Use a previously saved inventory JSON (faster)"
    ),
    log_level: str = typer.Option("INFO", help="Log level"),
) -> None:
    """Run full public reconnaissance and write Excel + Markdown reports."""
    settings = get_settings(str(config) if config else None)
    ensure_output_dirs(settings)
    setup_logging(settings.logs_path, level=log_level)

    orch = ReconOrchestrator(settings)
    payload = orch.run(
        skip_browser=skip_browser,
        skip_inventory=skip_inventory,
        use_cached_inventory=use_cached_inventory,
    )
    totals = payload.get("overview", {})
    console.print("[bold green]Reconnaissance complete[/bold green]")
    console.print(f"  States: {totals.get('states')}")
    console.print(f"  Districts: {totals.get('districts')}")
    console.print(f"  Constituencies: {totals.get('constituencies')}")
    console.print(f"  Excel: {settings.excel_path / 'eci_eroll_reconnaissance.xlsx'}")
    console.print(f"  Docs:  {settings.docs_path}")
    console.print(f"  JSON:  {settings.output_path / 'recon_master.json'}")


@app.command("inventory")
def inventory_only(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Run geo inventory only (public endpoints)."""
    from dataclasses import asdict

    from analyzer.inventory import InventoryBuilder

    settings = get_settings(str(config) if config else None)
    ensure_output_dirs(settings)
    setup_logging(settings.logs_path)
    inv = InventoryBuilder(settings).build()
    InventoryBuilder(settings).save(inv, settings.raw_path / "inventory")
    console.print(inv.totals)


@app.command("observe")
def observe_only(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Playwright observational pass only."""
    from dataclasses import asdict

    from browser.observer import BrowserObserver

    settings = get_settings(str(config) if config else None)
    ensure_output_dirs(settings)
    setup_logging(settings.logs_path)
    res = BrowserObserver(settings).observe_download_eroll()
    out = settings.raw_path / "browser_observation.json"
    BrowserObserver(settings).save(res, out)
    console.print(f"Saved {out} ({len(res.network_requests)} network events)")


if __name__ == "__main__":
    app()
