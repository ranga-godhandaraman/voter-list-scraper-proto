"""Configuration loading via YAML + environment overrides."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "settings.yaml"


class TargetConfig(BaseModel):
    site_url: str
    download_eroll_path: str
    gateway_url: str
    secondary_gateways: list[str] = Field(default_factory=list)
    application_name: str = "VSP"
    platform_type: str = "web"
    channel_id: str = "VSP"

    @property
    def download_eroll_url(self) -> str:
        return f"{self.site_url.rstrip('/')}{self.download_eroll_path}"


class HttpConfig(BaseModel):
    user_agent: str
    timeout_seconds: float = 45.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.5
    request_delay_seconds: float = 0.45
    verify_ssl: bool = True


class BrowserConfig(BaseModel):
    headless: bool = True
    navigation_timeout_ms: int = 60_000
    capture_network: bool = True
    capture_storage: bool = True
    max_wait_for_spa_ms: int = 15_000


class ReconConfig(BaseModel):
    probe_languages_per_state: bool = True
    skip_signed_endpoints: bool = True
    max_sample_pdfs: int = 0
    years_to_note: list[str] = Field(default_factory=list)


class OutputConfig(BaseModel):
    dir: str = "output"
    excel_dir: str = "excel"
    docs_dir: str = "docs"
    logs_dir: str = "logs"
    raw_dir: str = "output/raw"


class ComplianceConfig(BaseModel):
    respect_robots: bool = True
    no_mass_download: bool = True
    no_bypass_protections: bool = True
    identify_only_anti_bot: bool = True


class Settings(BaseSettings):
    """Root settings for the reconnaissance analyzer."""

    target: TargetConfig
    http: HttpConfig
    browser: BrowserConfig
    recon: ReconConfig
    output: OutputConfig
    compliance: ComplianceConfig
    project_root: Path = ROOT

    def resolve(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute():
            return path
        return self.project_root / path

    @property
    def output_path(self) -> Path:
        return self.resolve(self.output.dir)

    @property
    def excel_path(self) -> Path:
        return self.resolve(self.output.excel_dir)

    @property
    def docs_path(self) -> Path:
        return self.resolve(self.output.docs_dir)

    @property
    def logs_path(self) -> Path:
        return self.resolve(self.output.logs_dir)

    @property
    def raw_path(self) -> Path:
        return self.resolve(self.output.raw_dir)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return data


@lru_cache(maxsize=1)
def get_settings(config_path: str | None = None) -> Settings:
    """Load settings once; optional path override for tests/CLI."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    raw = _load_yaml(path)
    return Settings(**raw)


def ensure_output_dirs(settings: Settings | None = None) -> None:
    """Create output directories if missing."""
    cfg = settings or get_settings()
    for p in (cfg.output_path, cfg.excel_path, cfg.docs_path, cfg.logs_path, cfg.raw_path):
        p.mkdir(parents=True, exist_ok=True)
