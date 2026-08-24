"""SQLite + optional JSON tracking for download jobs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from loguru import logger

from downloader.models import DownloadRecord, DownloadStatus


_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id TEXT PRIMARY KEY,
    state_short TEXT NOT NULL,
    state_cd TEXT NOT NULL,
    state_name TEXT NOT NULL,
    year TEXT NOT NULL,
    roll_type_value TEXT NOT NULL,
    roll_type_label TEXT NOT NULL,
    district_cd TEXT NOT NULL,
    district_name TEXT NOT NULL,
    ac_number TEXT NOT NULL,
    ac_name TEXT NOT NULL,
    part_number TEXT NOT NULL,
    part_name TEXT NOT NULL,
    language TEXT NOT NULL,
    filename TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    url TEXT,
    status TEXT NOT NULL,
    file_size INTEGER,
    checksum_sha256 TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    downloaded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
CREATE INDEX IF NOT EXISTS idx_downloads_state_year ON downloads(state_short, year);
CREATE UNIQUE INDEX IF NOT EXISTS idx_downloads_unique_part
  ON downloads(state_short, year, roll_type_value, district_cd, ac_number, part_number, language);
"""


def make_record_id(
    state_short: str,
    year: str,
    roll_type_value: str,
    district_cd: str,
    ac_number: str,
    part_number: str,
    language: str,
) -> str:
    return "|".join(
        [
            state_short,
            year,
            roll_type_value,
            district_cd,
            str(ac_number),
            str(part_number),
            language,
        ]
    )


class DownloadStore:
    """Persistent download ledger (SQLite)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("Download store ready at {}", db_path)

    def close(self) -> None:
        self._conn.close()

    def upsert(self, record: DownloadRecord) -> None:
        record.updated_at = datetime.utcnow()
        data = record.model_dump()
        data["status"] = record.status.value
        data["created_at"] = record.created_at.isoformat()
        data["updated_at"] = record.updated_at.isoformat()
        data["downloaded_at"] = (
            record.downloaded_at.isoformat() if record.downloaded_at else None
        )
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data)
        updates = ", ".join(
            f"{k}=excluded.{k}"
            for k in data
            if k not in {"id", "created_at"}
        )
        sql = (
            f"INSERT INTO downloads ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}"
        )
        self._conn.execute(sql, data)
        self._conn.commit()

    def get(self, record_id: str) -> DownloadRecord | None:
        row = self._conn.execute(
            "SELECT * FROM downloads WHERE id = ?", (record_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def is_completed(self, record_id: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM downloads WHERE id = ?", (record_id,)
        ).fetchone()
        return bool(row and row["status"] == DownloadStatus.COMPLETED.value)

    def list_by_status(
        self, status: DownloadStatus, *, state_short: str | None = None
    ) -> list[DownloadRecord]:
        if state_short:
            rows = self._conn.execute(
                "SELECT * FROM downloads WHERE status = ? AND state_short = ?",
                (status.value, state_short),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM downloads WHERE status = ?", (status.value,)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def counts(self, state_short: str, year: str | None = None) -> dict[str, int]:
        sql = "SELECT status, COUNT(*) AS n FROM downloads WHERE state_short = ?"
        params: list[Any] = [state_short]
        if year:
            sql += " AND year = ?"
            params.append(year)
        sql += " GROUP BY status"
        out = {s.value: 0 for s in DownloadStatus}
        for row in self._conn.execute(sql, params):
            out[row["status"]] = int(row["n"])
        return out

    def export_json(self, path: Path, *, state_short: str | None = None) -> Path:
        if state_short:
            rows = self._conn.execute(
                "SELECT * FROM downloads WHERE state_short = ?", (state_short,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM downloads").fetchall()
        payload = [dict(r) for r in rows]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> DownloadRecord:
        d = dict(row)
        d["status"] = DownloadStatus(d["status"])
        d["created_at"] = datetime.fromisoformat(d["created_at"])
        d["updated_at"] = datetime.fromisoformat(d["updated_at"])
        if d.get("downloaded_at"):
            d["downloaded_at"] = datetime.fromisoformat(d["downloaded_at"])
        return DownloadRecord(**d)

    def bulk_pending(self, records: Iterable[DownloadRecord]) -> int:
        n = 0
        for rec in records:
            existing = self.get(rec.id)
            if existing and existing.status == DownloadStatus.COMPLETED:
                continue
            if existing is None:
                self.upsert(rec)
                n += 1
            elif existing.status in {DownloadStatus.FAILED, DownloadStatus.PENDING}:
                self.upsert(rec)
                n += 1
        return n
