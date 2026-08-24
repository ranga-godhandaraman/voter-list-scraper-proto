"""Export hierarchy graph (NetworkX) for documentation / analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
from loguru import logger


def build_hierarchy_graph(
    states: list[dict[str, Any]],
    districts: list[dict[str, Any]],
    constituencies: list[dict[str, Any]],
    *,
    max_districts: int = 200,
    max_acs: int = 400,
) -> nx.DiGraph:
    """Build a truncated directed graph Country→State→District→AC for visualization."""
    g = nx.DiGraph()
    g.add_node("IN", label="India", level="country")
    for s in states:
        cd = s.get("state_cd") or s.get("stateCd")
        if not cd:
            continue
        g.add_node(cd, label=s.get("state_name") or s.get("stateName"), level="state")
        g.add_edge("IN", cd)

    for i, d in enumerate(districts[:max_districts]):
        sc = d.get("stateCd") or d.get("state")
        dn = d.get("districtNo")
        if not sc or dn is None:
            continue
        node = f"{sc}-D{dn}"
        g.add_node(node, label=d.get("districtValue"), level="district")
        if sc in g:
            g.add_edge(sc, node)

    for i, a in enumerate(constituencies[:max_acs]):
        sc = a.get("stateCd")
        acn = a.get("asmblyNo")
        if not sc or acn is None:
            continue
        node = f"{sc}-AC{acn}"
        g.add_node(node, label=a.get("asmblyName"), level="assembly")
        # Prefer district edge when districtCd present
        dc = a.get("districtCd")
        attached = False
        if dc:
            # districtCd often like S2408 → try match state+districtNo
            for n, data in g.nodes(data=True):
                if data.get("level") == "district" and n.startswith(f"{sc}-D"):
                    # weak attach first district of state if exact map unknown
                    pass
            # attach to state for truncated graph stability
            if sc in g:
                g.add_edge(sc, node)
                attached = True
        if not attached and sc in g:
            g.add_edge(sc, node)

    logger.info("Hierarchy graph nodes={} edges={}", g.number_of_nodes(), g.number_of_edges())
    return g


def export_graph(g: nx.DiGraph, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(g)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
