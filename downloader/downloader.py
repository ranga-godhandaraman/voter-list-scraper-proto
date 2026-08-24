"""Electoral roll PDF downloader — district-scoped, batch captcha per AC.

Uses public HTTP for geo, Playwright for signed SPA calls, and browser captcha
(once per assembly via select-all batching).
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
from loguru import logger
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from downloader.discovery import GeoDiscovery, SpaFormDriver, pick_language
from downloader.district import resolve_district_by_name
from downloader.models import (
    DownloadRecord,
    DownloadStatus,
    DownloaderConfig,
    PartInfo,
    RollTypeInfo,
    RunSummary,
)
from downloader.proxy import ProxyPool, mask_proxy
from downloader.roll_picker import draft_roll_available, pick_roll_interactive
from downloader.state_mapping import StateInfo, resolve_state
from downloader.storage import DownloadStore, make_record_id
from downloader.utils import build_rel_path, part_filename, sha256_file
from utils.config import get_settings

console = Console()


class ErollDownloader:
    """Discover + download electoral-roll PDFs for one district."""

    def __init__(self, config: DownloaderConfig) -> None:
        self.config = config
        self.state: StateInfo = resolve_state(config.state)
        self.settings = get_settings()
        self.proxy_pool = (
            ProxyPool.from_file(config.proxy_file) if config.proxy_file else None
        )
        initial_proxy = self.proxy_pool.current if self.proxy_pool else None
        self.geo = GeoDiscovery(
            self.settings, delay=config.delay, proxy=initial_proxy
        )
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.store = DownloadStore(config.resolved_db_path())
        self.summary = RunSummary(
            state_short=self.state.short_code,
            state_name=self.state.name,
            state_cd=self.state.eci_state_cd,
            revision_used=None,
            roll_type=None,
            language=config.language,
            dry_run=config.dry_run,
            output_dir=str(self.output_dir.resolve()),
        )

    def run(self) -> RunSummary:
        started = time.monotonic()
        if not self.config.district_name and not self.config.dry_run:
            raise ValueError(
                "--district is required for downloads. "
                "Example: python download_eroll.py -s GJ --district Ahmedabad"
            )

        logger.info(
            "Starting {} for {} ({}) district={}",
            "dry-run" if self.config.dry_run else "download",
            self.state.short_code,
            self.state.eci_state_cd,
            self.config.district_name,
        )

        districts = self._geo_call(lambda: self.geo.districts(self.state))
        assemblies = self._geo_call(lambda: self.geo.assemblies(self.state))

        target_district = None
        district_assemblies = assemblies
        if self.config.district_name:
            target_district = resolve_district_by_name(districts, self.config.district_name)
            console.print(
                f"[cyan]District[/cyan] {target_district.district_name} "
                f"({target_district.district_cd})"
            )
            district_assemblies = [
                a for a in assemblies if a.district_cd == target_district.district_cd
            ]
            if not district_assemblies:
                self.summary.notes.append(
                    f"No assemblies found for district {target_district.district_name}"
                )
            self.summary.districts_scanned = 1
            self.summary.assemblies_scanned = len(district_assemblies)

        elif self.config.dry_run and districts:
            # Dry-run without --district: preview first district only
            target_district = districts[0]
            console.print(
                f"[yellow]Dry-run without --district: previewing "
                f"{target_district.district_name} only.[/yellow]"
            )
            district_assemblies = [
                a for a in assemblies if a.district_cd == target_district.district_cd
            ]
            self.summary.districts_scanned = 1
            self.summary.assemblies_scanned = len(district_assemblies)
        else:
            self.summary.districts_scanned = len(districts)
            self.summary.assemblies_scanned = len(assemblies)

        use_headless = self.config.headless if self.config.dry_run else False
        initial_proxy = self.proxy_pool.current if self.proxy_pool else None
        if self.proxy_pool:
            console.print(
                f"[cyan]Proxy[/cyan] {mask_proxy(initial_proxy or '')} "
                f"({len(self.proxy_pool)} in pool)"
            )
        with SpaFormDriver(
            headless=use_headless,
            user_agent=self.config.user_agent,
            delay=self.config.delay,
            proxy=initial_proxy,
        ) as spa:
            self._open_spa(spa)
            spa.select_state(self.state)
            year, roll = self._resolve_revision(spa, target_district)
            if not year or not roll:
                self.summary.notes.append("No downloadable roll type found.")
                self.summary.elapsed_seconds = time.monotonic() - started
                return self.summary

            self.summary.revision_used = year
            self.summary.roll_type = f"{roll.label} ({roll.value})"

            parts = self._discover_parts(
                spa,
                target_district,
                district_assemblies,
                year,
                roll,
            )
            self.summary.parts_found = len(parts)
            logger.info("Discovered {} parts", len(parts))

            if not parts and not self.config.dry_run:
                console.print(
                    "[red]No parts found for this district — nothing to download.[/red]\n"
                    "[dim]If the portal form changed, check logs or re-run with --verbose.[/dim]"
                )

            self.store.bulk_pending([self._to_record(p) for p in parts])
            self.store.export_json(
                self.output_dir / f"{self.state.short_code}_manifest.json",
                state_short=self.state.short_code,
            )

            if self.config.dry_run:
                self.summary.notes.append(
                    f"Dry run — listed {len(parts)} parts; no PDFs downloaded."
                )
                self.summary.elapsed_seconds = time.monotonic() - started
                return self.summary

            self._download_district_batches(spa, parts)

        self.summary.elapsed_seconds = time.monotonic() - started
        return self.summary

    def _geo_call(self, fn):
        """Run a geo HTTP call; rotate proxy on 407 / connection failures."""
        attempts = len(self.proxy_pool) if self.proxy_pool else 1
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                return fn()
            except requests.exceptions.ProxyError as exc:
                last_exc = exc
                if not self.proxy_pool or i + 1 >= attempts:
                    raise
                new_proxy = self.proxy_pool.rotate()
                self.geo.set_proxy(new_proxy)
                console.print(
                    f"[yellow]Proxy auth/connection failed — trying "
                    f"{mask_proxy(new_proxy)}[/yellow]"
                )
        raise last_exc or RuntimeError("Geo call failed via proxy pool")

    def _open_spa(self, spa: SpaFormDriver) -> None:
        """Open download form; rotate through proxy pool on Akamai/login failures."""
        if not self.proxy_pool:
            spa.open()
            return

        last_exc: Exception | None = None
        for i in range(len(self.proxy_pool)):
            try:
                spa.open()
                return
            except RuntimeError as exc:
                last_exc = exc
                if i + 1 >= len(self.proxy_pool):
                    break
                new_proxy = self.proxy_pool.rotate()
                spa.set_proxy(new_proxy)
                self.geo.set_proxy(new_proxy)
                console.print(
                    f"[yellow]Proxy blocked — retrying with {mask_proxy(new_proxy)}[/yellow]"
                )
        raise last_exc or RuntimeError("Could not open download form via proxy pool")

    def _rotate_proxy(self, spa: SpaFormDriver) -> bool:
        """Rotate to next proxy on both HTTP and browser. Returns False if no pool."""
        if not self.proxy_pool:
            return False
        new_proxy = self.proxy_pool.rotate()
        spa.set_proxy(new_proxy)
        self.geo.set_proxy(new_proxy)
        console.print(f"[yellow]Switched to proxy {mask_proxy(new_proxy)}[/yellow]")
        return True

    def _discover_parts(
        self,
        spa: SpaFormDriver,
        target_district,
        assemblies: list,
        year: str,
        roll: RollTypeInfo,
    ) -> list[PartInfo]:
        if not target_district:
            return []

        parts: list[PartInfo] = []
        acs = assemblies
        if self.config.max_assemblies:
            acs = acs[: self.config.max_assemblies]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        ) as progress:
            task = progress.add_task("Scanning assemblies", total=len(acs) or 1)
            spa.select_district(target_district.district_cd)
            for ac in acs:
                progress.update(task, description=f"AC {ac.ac_number} {ac.ac_name}")
                if not spa.select_assembly_by_number(ac.ac_number, ac.ac_name):
                    logger.warning("AC select failed: {} {}", ac.ac_number, ac.ac_name)
                    progress.advance(task)
                    continue
                langs = spa.language_options()
                if not langs:
                    langs = list(self.geo.languages(self.state, ac.ac_number).items())
                chosen = pick_language(langs, self.config.language)
                if not chosen:
                    progress.advance(task)
                    continue
                lang_cd, _ = chosen
                self.summary.language = lang_cd
                if spa.language_options():
                    spa.select_language(lang_cd)
                for part_no, part_name in spa.scrape_parts():
                    if (
                        str(part_no) == str(ac.ac_number)
                        and part_name.strip() == ac.ac_name.strip()
                    ):
                        continue
                    parts.append(
                        PartInfo(
                            part_number=part_no,
                            part_name=part_name,
                            state_cd=self.state.eci_state_cd,
                            district_cd=target_district.district_cd,
                            district_name=target_district.district_name,
                            ac_number=ac.ac_number,
                            ac_name=ac.ac_name,
                            year=year,
                            roll_type_value=roll.value,
                            roll_type_label=roll.label,
                            language=lang_cd,
                        )
                    )
                progress.advance(task)
        return parts

    def _resolve_revision(self, spa: SpaFormDriver, target_district) -> tuple[str | None, RollTypeInfo | None]:
        years = spa.available_years()
        if self.config.revision and self.config.revision.lower() != "auto":
            years = [self.config.revision] + [y for y in years if y != self.config.revision]
        else:
            years = sorted(set(years), reverse=True)

        district_label = target_district.district_name if target_district else self.state.name
        logger.info("Trying revision years: {}", years)

        for year in years:
            try:
                spa.select_year(year)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Year {} failed: {}", year, exc)
                continue

            rolls = spa.roll_types()
            if not rolls:
                continue
            logger.info("Year {} → {} roll types", year, len(rolls))

            draft = draft_roll_available(rolls)
            if draft is not None:
                spa.select_roll_type(draft.value)
                if spa.has_district_select() and spa.district_options():
                    console.print(f"[green]Using SIR Draft:[/green] {draft.label}")
                    return year, draft

            # Draft missing — ask in terminal which roll to use
            pickable = [r for r in rolls if r.kind not in {"SUPP"}]
            if not pickable:
                pickable = rolls
            chosen = pick_roll_interactive(
                pickable,
                district_name=district_label,
                year=year,
                prefer_kinds=self.config.prefer_roll_kinds,
                roll_index=self.config.roll_index,
            )
            spa.select_roll_type(chosen.value)
            if spa.has_district_select() and spa.district_options():
                return year, chosen

        return None, None

    def _download_district_batches(self, spa: SpaFormDriver, parts: list[PartInfo]) -> None:
        """One browser captcha per AC — downloads all parts in that AC (select-all)."""
        by_ac: dict[tuple[str, str, str], list[PartInfo]] = defaultdict(list)
        for p in parts:
            by_ac[(p.district_cd, p.ac_number, p.language)].append(p)

        for (_dist_cd, ac_no, _lang), group in by_ac.items():
            sample = group[0]
            pending: list[tuple[PartInfo, DownloadRecord, Path]] = []
            for part in sorted(group, key=lambda x: int(x.part_number)):
                record = self._to_record(part)
                dest = self.output_dir / record.rel_path
                if self._should_skip(record, dest):
                    self.summary.skipped += 1
                    continue
                pending.append((part, record, dest))

            if not pending:
                continue

            console.print()
            console.print(
                f"[bold]AC {sample.ac_number} — {sample.ac_name}[/bold] "
                f"({len(pending)} parts, [cyan]paginated batches ~10/page[/cyan])"
            )

            try:
                self._prepare_form(spa, sample)
            except Exception as exc:  # noqa: BLE001
                for part, record, _ in pending:
                    self._fail_record(record, f"form prepare failed: {exc}")
                continue

            attempts = 0
            while pending and attempts < 3:
                attempts += 1
                try:
                    part_downloads = [(part.part_number, dest) for part, _, dest in pending]
                    saved = spa.download_selected_parts_batch(
                        part_downloads=part_downloads,
                        captcha_timeout_seconds=self.config.captcha_timeout_seconds,
                    )
                    saved_paths = {p.resolve() for p in saved}
                    for part, record, dest in pending:
                        path = dest
                        if dest.resolve() in saved_paths and path.exists() and path.stat().st_size > 0:
                            self._complete_record(record, path)
                        elif attempts >= 3:
                            self._fail_record(record, "not downloaded")
                    pending = [
                        (part, record, dest)
                        for part, record, dest in pending
                        if dest.resolve() not in saved_paths
                        or not dest.exists()
                        or dest.stat().st_size == 0
                    ]
                    if not pending:
                        break
                except Exception as exc:  # noqa: BLE001
                    logger.error("Batch download failed for AC {}: {}", ac_no, exc)
                    if attempts >= 3:
                        for part, record, _ in pending:
                            self._fail_record(record, str(exc))
                    elif "login" in str(exc).lower() and self._rotate_proxy(spa):
                        console.print("[yellow]Rotating proxy and reopening form…[/yellow]")
                        try:
                            self._open_spa(spa)
                            self._prepare_form(spa, sample)
                            attempts -= 1
                        except Exception:
                            break
                    else:
                        console.print("[yellow]Retrying with a fresh captcha…[/yellow]")
                        try:
                            self._prepare_form(spa, sample)
                        except Exception:
                            break

            time.sleep(self.config.delay)

    def _should_skip(self, record: DownloadRecord, dest: Path) -> bool:
        if (
            self.config.resume
            and not self.config.force
            and dest.exists()
            and dest.stat().st_size > 0
        ):
            self.summary.already_existing += 1
            record.status = DownloadStatus.COMPLETED
            record.file_size = dest.stat().st_size
            record.downloaded_at = datetime.utcnow()
            try:
                record.checksum_sha256 = sha256_file(dest)
            except Exception:
                pass
            self.store.upsert(record)
            return True
        if (
            self.config.resume
            and not self.config.force
            and self.store.is_completed(record.id)
        ):
            self.summary.already_existing += 1
            return True
        return False

    def _prepare_form(self, spa: SpaFormDriver, part: PartInfo) -> None:
        spa.prepare_form_for_ac(
            state=self.state,
            year=part.year,
            roll_value=part.roll_type_value,
            district_cd=part.district_cd,
            ac_number=part.ac_number,
            ac_name=part.ac_name,
            language=part.language,
        )

    def _complete_record(self, record: DownloadRecord, path: Path) -> None:
        record.status = DownloadStatus.COMPLETED
        record.file_size = path.stat().st_size
        record.checksum_sha256 = sha256_file(path)
        record.downloaded_at = datetime.utcnow()
        record.error = None
        self.store.upsert(record)
        self.summary.pdfs_downloaded += 1
        logger.info("Saved {}", path)

    def _fail_record(self, record: DownloadRecord, reason: str) -> None:
        record.status = DownloadStatus.FAILED
        record.error = reason
        record.retry_count += 1
        self.store.upsert(record)
        self.summary.failed += 1

    def _to_record(self, part: PartInfo) -> DownloadRecord:
        filename = part_filename(part.part_number, part.part_name, part.language)
        rel = build_rel_path(
            state_short=self.state.short_code,
            year=part.year,
            district_name=part.district_name,
            ac_name=part.ac_name,
            filename=filename,
            language=part.language,
        )
        rid = make_record_id(
            self.state.short_code,
            part.year,
            part.roll_type_value,
            part.district_cd,
            part.ac_number,
            part.part_number,
            part.language,
        )
        return DownloadRecord(
            id=rid,
            state_short=self.state.short_code,
            state_cd=self.state.eci_state_cd,
            state_name=self.state.name,
            year=part.year,
            roll_type_value=part.roll_type_value,
            roll_type_label=part.roll_type_label,
            district_cd=part.district_cd,
            district_name=part.district_name,
            ac_number=part.ac_number,
            ac_name=part.ac_name,
            part_number=part.part_number,
            part_name=part.part_name,
            language=part.language,
            filename=filename,
            rel_path=str(rel),
        )
