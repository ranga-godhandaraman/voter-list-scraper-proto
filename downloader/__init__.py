"""Electoral roll PDF downloader package (extends recon; does not replace it)."""

from downloader.models import DownloaderConfig, RunSummary
from downloader.state_mapping import STATES, resolve_state
from downloader.downloader import ErollDownloader

__all__ = [
    "DownloaderConfig",
    "RunSummary",
    "STATES",
    "resolve_state",
    "ErollDownloader",
]
