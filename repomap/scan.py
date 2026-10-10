"""Scan a folder: Python gets the deep ast analyzer, everything else goes through tree-sitter."""

from __future__ import annotations

from pathlib import Path

from .analyzer import Analyzer
from .polyglot import Polyglot


def scan(root: str | Path, include_tests: bool = False) -> dict:
    root = Path(root).resolve()
    py = Analyzer(root, include_tests=include_tests).analyze()
    for n in py["nodes"]:
        n["lang"] = "Python"
    poly = Polyglot(root, include_tests=include_tests).analyze()

    nodes = py["nodes"] + poly["nodes"]
    edges = py["edges"] + poly["edges"]
    languages = dict(poly.get("languages", {}))
    if py["stats"]["files"]:
        languages["Python"] = {"files": py["stats"]["files"], "lines": py["stats"]["lines"]}
    languages = dict(sorted(languages.items(), key=lambda kv: -kv[1]["lines"]))

    stats = {
        "files": sum(v["files"] for v in languages.values()),
        "lines": sum(v["lines"] for v in languages.values()),
        "functions": sum(1 for n in nodes if n["kind"] == "function"),
        "methods": sum(1 for n in nodes if n["kind"] == "method"),
        "classes": sum(1 for n in nodes if n["kind"] == "class"),
        "data": sum(1 for n in nodes if n["kind"] == "data"),
        "entries": sum(1 for n in nodes if n.get("entry")),
        "edges": len(edges),
    }
    return {"root": root.name, "nodes": nodes, "edges": edges, "stats": stats,
            "languages": languages, "warnings": py["warnings"] + poly["warnings"]}
