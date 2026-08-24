#!/usr/bin/env python3
"""Entry point: python download_eroll.py --state AP

Delegates to ``downloader.cli`` without modifying the recon analyzer package.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable when run as a script
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from downloader.cli import app

if __name__ == "__main__":
    app()
