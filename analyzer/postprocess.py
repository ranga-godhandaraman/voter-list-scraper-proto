"""Generate hierarchy graph artifact after recon."""

from __future__ import annotations

import json
from pathlib import Path

from analyzer.graph_export import build_hierarchy_graph, export_graph
from parser.pdf_meta import analyze_samples
from utils.config import get_settings


def main() -> None:
    settings = get_settings()
    master = settings.output_path / "recon_master.json"
    if not master.exists():
        raise SystemExit("Run analyzer.cli run first")
    data = json.loads(master.read_text(encoding="utf-8"))
    g = build_hierarchy_graph(data.get("states", []), data.get("districts", []), data.get("constituencies", []))
    out = export_graph(g, settings.raw_path / "hierarchy_graph.json")
    samples = analyze_samples(settings.raw_path / "sample_pdfs")
    (settings.raw_path / "pdf_metadata.json").write_text(
        json.dumps(samples or [{"note": "No local sample PDFs; mass download skipped by policy"}], indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
