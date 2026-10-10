"""Turns a graph dict into one self-contained HTML file (works offline)."""

import html
import json
from pathlib import Path

HERE = Path(__file__).parent


def render_html(graph: dict, title: str | None = None) -> str:
    template = (HERE / "template.html").read_text(encoding="utf-8")
    elk = (HERE / "vendor" / "elk.bundled.js").read_text(encoding="utf-8")
    data = json.dumps(graph, separators=(",", ":"))
    # Keep very large repos under ~12 MB by trimming the code previews, never the graph.
    for limit in (60, 30, 12):
        if len(data) < 12_000_000:
            break
        for n in graph["nodes"]:
            lines = n.get("source", "").split("\n")
            if len(lines) > limit:
                n["source"] = "\n".join(lines[:limit]) + f"\n… {len(lines) - limit} more lines"
        data = json.dumps(graph, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    page_title = html.escape(title or f"{graph['root']} code map")
    return (template
            .replace("__TITLE__", page_title)
            .replace("/*__ELK__*/", elk.replace("</script", "<\\/script"))
            .replace("__GRAPH_JSON__", data))
