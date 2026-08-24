"""Pydantic models for the electoral-roll downloader."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DownloadStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class RollTypeInfo(BaseModel):
    """A roll type option from the SPA (e.g. Final Roll - 2025)."""

    value: str  # e.g. S01-2025-FIR
    label: str
    year: str
    kind: str = ""  # FIR / DR / SUPP / unknown


class DistrictInfo(BaseModel):
    district_cd: str
    district_name: str
    state_cd: str


class AssemblyInfo(BaseModel):
    ac_number: str
    ac_name: str
    district_cd: str
    state_cd: str
    category: str | None = None


class PartInfo(BaseModel):
    part_number: str
    part_name: str
    state_cd: str
    district_cd: str
    district_name: str
    ac_number: str
    ac_name: str
    year: str
    roll_type_value: str
    roll_type_label: str
    language: str


class DownloadRecord(BaseModel):
    """Persisted download tracking row."""

    id: str
    state_short: str
    state_cd: str
    state_name: str
    year: str
    roll_type_value: str
    roll_type_label: str
    district_cd: str
    district_name: str
    ac_number: str
    ac_name: str
    part_number: str
    part_name: str
    language: str
    filename: str
    rel_path: str
    url: str | None = None
    status: DownloadStatus = DownloadStatus.PENDING
    file_size: int | None = None
    checksum_sha256: str | None = None
    retry_count: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    downloaded_at: datetime | None = None


class RunSummary(BaseModel):
    state_short: str
    state_name: str
    state_cd: str
    revision_used: str | None
    roll_type: str | None
    language: str | None
    districts_scanned: int = 0
    assemblies_scanned: int = 0
    parts_found: int = 0
    pdfs_downloaded: int = 0
    already_existing: int = 0
    skipped: int = 0
    failed: int = 0
    dry_run: bool = False
    elapsed_seconds: float = 0.0
    output_dir: str = ""
    notes: list[str] = Field(default_factory=list)

    def print_rich(self) -> None:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="Electoral Roll Download Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        rows = [
            ("State", f"{self.state_short} — {self.state_name} ({self.state_cd})"),
            ("Revision used", self.revision_used or "n/a"),
            ("Roll type", self.roll_type or "n/a"),
            ("Language", self.language or "n/a"),
            ("Districts scanned", str(self.districts_scanned)),
            ("Assemblies scanned", str(self.assemblies_scanned)),
            ("Parts found", str(self.parts_found)),
            ("PDFs downloaded", str(self.pdfs_downloaded)),
            ("Already existing", str(self.already_existing)),
            ("Skipped", str(self.skipped)),
            ("Failed", str(self.failed)),
            ("Dry run", str(self.dry_run)),
            ("Elapsed (s)", f"{self.elapsed_seconds:.1f}"),
            ("Output", self.output_dir),
        ]
        for k, v in rows:
            table.add_row(k, v)
        console.print(table)
        for note in self.notes:
            console.print(f"[yellow]• {note}[/yellow]")


class DownloaderConfig(BaseModel):
    """Runtime configuration for a download run."""

    state: str
    revision: str = "auto"
    language: str | None = None
    prefer_roll_kinds: list[str] = Field(
        default_factory=lambda: ["DR", "DRAFT", "FIR", "FINAL"]
    )
    output_dir: Path = Path("downloads")
    delay: float = 1.0
    workers: int = 1
    resume: bool = True
    force: bool = False
    verbose: bool = False
    dry_run: bool = False
    summary: bool = True
    headless: bool = False  # headed for downloads; use --headless for dry-run only
    captcha_timeout_seconds: int = 300
    max_retries: int = 3
    max_districts: int | None = None
    max_assemblies: int | None = None
    district_name: str | None = None
    roll_index: int | None = None  # non-interactive roll pick when draft missing
    batch_per_ac: bool = True  # one terminal captcha per AC (select all parts)
    years_fallback_order: list[str] = Field(default_factory=list)  # empty → read from SPA
    db_path: Path | None = None
    user_agent: str = ""  # empty → realistic Chrome UA for SPA (Akamai-safe)
    proxy_file: Path | None = None  # optional .txt list; omit = local IP

    def resolved_db_path(self) -> Path:
        if self.db_path:
            return self.db_path
        return self.output_dir / "downloads.sqlite"
