"""Terminal roll-type selection when SIR Draft is unavailable."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from downloader.discovery import pick_preferred_roll
from downloader.models import RollTypeInfo

console = Console()


def draft_roll_available(rolls: list[RollTypeInfo]) -> RollTypeInfo | None:
    for roll in rolls:
        blob = f"{roll.value} {roll.label}".upper()
        if roll.kind in {"DR", "DRAFT"} and "SIR" in blob:
            return roll
    for roll in rolls:
        if roll.kind in {"DR", "DRAFT"}:
            return roll
    return None


def print_roll_menu(
    rolls: list[RollTypeInfo],
    *,
    district_name: str,
    year: str,
    draft_missing: bool,
) -> None:
    if draft_missing:
        console.print()
        console.print(
            f"[yellow]SIR Draft is not available for {district_name} "
            f"(revision {year}).[/yellow]"
        )
        console.print("[cyan]Choose a roll type to download:[/cyan]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Roll type")
    table.add_column("Code", style="dim")
    for i, roll in enumerate(rolls, start=1):
        table.add_row(str(i), roll.label, roll.value)
    console.print(table)


def pick_roll_interactive(
    rolls: list[RollTypeInfo],
    *,
    district_name: str,
    year: str,
    prefer_kinds: list[str],
    roll_index: int | None = None,
) -> RollTypeInfo:
    if not rolls:
        raise RuntimeError(f"No roll types listed for {district_name} / {year}")

    draft = draft_roll_available(rolls)
    if draft is not None:
        console.print(
            f"[green]Using SIR Draft:[/green] {draft.label} ({draft.value})"
        )
        return draft

    preferred = pick_preferred_roll(rolls, prefer_kinds)
    if roll_index is not None:
        if roll_index < 1 or roll_index > len(rolls):
            raise ValueError(f"--roll-index must be 1–{len(rolls)}")
        return rolls[roll_index - 1]

    print_roll_menu(
        rolls, district_name=district_name, year=year, draft_missing=True
    )
    while True:
        raw = input("Enter roll type number: ").strip()
        if not raw.isdigit():
            console.print("[red]Enter a number from the list.[/red]")
            continue
        idx = int(raw)
        if 1 <= idx <= len(rolls):
            chosen = rolls[idx - 1]
            console.print(f"[green]Selected:[/green] {chosen.label}")
            return chosen
        console.print(f"[red]Enter a number between 1 and {len(rolls)}.[/red]")
