"""
Diff mode: compare two versions of a codebase structurally.

Both versions are scanned with the normal analyzers. Symbols are matched by a
stable key (file + qualified name, with an ordinal for duplicates instead of a
line number), so moving code around inside a file doesn't look like a change.

For every symbol the result says: added, changed, removed or unchanged.
For every link (calls, creates, has, ...): added or removed.
Changed symbols carry a line diff of their own body, the signature change if
any, and short notes like "now calls X" / "no longer calls Y".
"""

from __future__ import annotations

import difflib
import hashlib
import re
import subprocess
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

LINK_TYPES = ("calls", "creates", "maybe_calls", "has", "extends", "raises", "uses")


# ------------------------------------------------------------------ git snapshots
def git(args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def resolve_ref(repo: Path, ref: str) -> tuple[str, str]:
    """-> (full sha, short label). Raises SystemExit with a clear message."""
    code, out, err = git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], repo)
    if code != 0:
        raise SystemExit(f"Can't find '{ref}' in this repository. Try a branch name, tag, "
                         "commit, HEAD~1, or origin/main (run `git fetch` first).")
    sha = out.strip()
    return sha, f"{ref} ({sha[:7]})"


def snapshot(repo: Path, ref: str, subdir: str = "") -> Path:
    """Extract the tracked files of `ref` into a temp folder (no checkout, no worktree)."""
    dest = Path(tempfile.mkdtemp(prefix="repomap-base-"))
    args = ["archive", "--format=tar", ref] + ([subdir] if subdir else [])
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if r.returncode != 0:
        msg = r.stderr.decode("utf-8", "replace").strip()
        if subdir and "did not match" in msg:
            dest.mkdir(parents=True, exist_ok=True)  # folder didn't exist at that ref
            return dest
        raise SystemExit(f"Couldn't read {ref}: {msg}")
    with tarfile.open(fileobj=BytesIO(r.stdout)) as tar:
        safe = [m for m in tar.getmembers()
                if not (m.name.startswith("/") or ".." in Path(m.name).parts) and (m.isfile() or m.isdir())]
        extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}  # Python 3.12+: safe extraction
        tar.extractall(dest, members=safe, **extra)
    return dest / subdir if subdir else dest


# ------------------------------------------------------------------ matching
def _base_key(n):
    if n["kind"] == "entry" and ":route:" in n["id"]:
        return f"{n['file']}::route::{n['name']}"
    return re.sub(r"#L\d+$", "", f"{n['file']}::{n['qualname']}")


def keyed(graph):
    """Stable key -> node. Duplicates (overloads, two routes on the same path) get ~1, ~2 by order."""
    groups = {}
    for n in graph["nodes"]:
        groups.setdefault(_base_key(n), []).append(n)
    out = {}
    for k, ns in groups.items():
        ns.sort(key=lambda n: n["line"])
        for i, n in enumerate(ns):
            out[k if i == 0 else f"{k}~{i}"] = n
    return out


def _lines(root: Path, cache: dict, rel: str):
    if rel not in cache:
        try:
            cache[rel] = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            cache[rel] = []
    return cache[rel]


def _own_text(n, by_parent, root, cache):
    """A symbol's own source: classes exclude their methods so a method edit
    doesn't mark the whole class as changed."""
    lines = _lines(root, cache, n["file"])
    lo, hi = n["line"], n["end_line"]
    if n["kind"] == "entry" and n["qualname"] == "<run>":
        return None  # whole-file pseudo node: compare its links instead
    skip = set()
    for c in by_parent.get(n["id"], []):
        skip.update(range(c["line"], c["end_line"] + 1))
    body = [lines[i - 1].rstrip() for i in range(lo, min(hi, len(lines)) + 1) if i not in skip]
    while body and not body[-1].strip():
        body.pop()
    return body


def _digest(lines):
    # Ignore formatting: indentation, trailing spaces and runs of spaces inside a line.
    norm = "\n".join(re.sub(r"\s+", " ", l.strip()) for l in lines if l.strip())
    return hashlib.sha1(norm.encode()).hexdigest()


# ------------------------------------------------------------------ compare
def compare(old: dict, new: dict, old_root: Path, new_root: Path,
            base_label: str, head_label: str, base_sha: str | None = None) -> dict:
    ok, nk = keyed(old), keyed(new)
    old_id2key = {n["id"]: k for k, n in ok.items()}
    new_id2key = {n["id"]: k for k, n in nk.items()}
    oc, nc = {}, {}
    old_children, new_children = {}, {}
    for n in old["nodes"]:
        if n.get("parent"):
            old_children.setdefault(n["parent"], []).append(n)
    for n in new["nodes"]:
        if n.get("parent"):
            new_children.setdefault(n["parent"], []).append(n)

    def ekeys(graph, id2key):
        out = {}
        for e in graph["edges"]:
            s, t = id2key.get(e["source"]), id2key.get(e["target"])
            if s and t:
                out[(s, t, e["type"])] = e
        return out

    oe, ne = ekeys(old, old_id2key), ekeys(new, new_id2key)
    out_old, out_new = {}, {}
    for (s, t, ty) in oe:
        out_old.setdefault(s, set()).add((t, ty))
    for (s, t, ty) in ne:
        out_new.setdefault(s, set()).add((t, ty))

    status, details = {}, {}
    for k, n in nk.items():
        if k not in ok:
            status[k] = "added"
            continue
        o = ok[k]
        ot = _own_text(o, old_children, old_root, oc)
        nt = _own_text(n, new_children, new_root, nc)
        if ot is None or nt is None:
            changed = out_old.get(k, set()) != out_new.get(k, set())
        else:
            changed = _digest(ot) != _digest(nt)
        if changed:
            status[k] = "changed"
            d = {}
            if ot is not None and nt is not None:
                diff = list(difflib.unified_diff(ot, nt, lineterm="", n=2))[2:]
                if len(diff) > 160:
                    diff = diff[:160] + [f"… {len(diff) - 160} more diff lines"]
                d["diff"] = "\n".join(diff)
                d["old_start"], d["new_start"] = o["line"], n["line"]
            of, nf = o.get("fields") or [], n.get("fields") or []
            if of != nf and (of or nf):
                d["fields_added"] = [f for f in nf if f not in of]
                d["fields_removed"] = [f for f in of if f not in nf]
            if o.get("signature") and n.get("signature") and \
                    re.sub(r"\s+", "", o["signature"]) != re.sub(r"\s+", "", n["signature"]):
                d["old_signature"] = o["signature"]
            details[k] = d
        else:
            status[k] = "unchanged"
    for k in ok:
        if k not in nk:
            status[k] = "removed"

    # ---------------------------------------------------------- merged graph
    nodes, idmap_old = [], {}
    for k, n in nk.items():
        m = dict(n)
        m["change"] = status[k]
        if k in details:
            m.update(details[k])
        nodes.append(m)
    for k, o in ok.items():
        if status[k] != "removed":
            idmap_old[o["id"]] = nk[k]["id"]
    for k, o in ok.items():
        if status[k] == "removed":
            idmap_old[o["id"]] = "removed:" + o["id"]
    for k, o in ok.items():
        if status[k] != "removed":
            continue
        m = dict(o)
        m["id"] = idmap_old[o["id"]]
        m["change"] = "removed"
        if o.get("parent"):
            m["parent"] = idmap_old.get(o["parent"], "removed:" + o["parent"])
        if base_sha:
            m["sha"] = base_sha
        nodes.append(m)

    edges = []
    for key, e in ne.items():
        edges.append({**e, "change": "same" if key in oe else "added"})
    for key, e in oe.items():
        if key in ne:
            continue
        s, t = idmap_old.get(e["source"]), idmap_old.get(e["target"])
        if s and t:
            edges.append({**e, "source": s, "target": t, "change": "removed"})

    # ---------------------------------------------------------- notes per change
    names_new = {n["id"]: n for n in nodes}

    def disp(nid):
        n = names_new.get(nid)
        if not n:
            return nid
        if n["kind"] == "entry":
            return n["name"]
        return n["qualname"] + ("" if n["kind"] in ("class", "data") else "()")

    callers = {}
    for e in edges:
        if e["change"] != "removed" and e["type"] in ("calls", "creates", "maybe_calls"):
            callers.setdefault(e["target"], set()).add(e["source"])

    added_out, removed_out = {}, {}
    for e in edges:
        if e["type"] not in ("calls", "creates", "maybe_calls", "has", "extends", "raises"):
            continue
        if e["change"] == "added":
            added_out.setdefault(e["source"], []).append(e)
        elif e["change"] == "removed":
            removed_out.setdefault(e["source"], []).append(e)

    verbs_add = {"calls": "now calls", "maybe_calls": "probably now calls", "creates": "now creates",
                 "has": "now holds", "extends": "now extends", "raises": "can now raise"}
    verbs_rm = {"calls": "no longer calls", "maybe_calls": "no longer calls", "creates": "no longer creates",
                "has": "no longer holds", "extends": "no longer extends", "raises": "no longer raises"}

    summary = []
    for n in nodes:
        ch = n.get("change")
        if ch not in ("added", "changed", "removed"):
            continue
        notes = []
        if ch == "added" and n.get("entry"):
            notes.append(f"new entry point: {n['entry']}")
        if ch == "removed" and n.get("entry"):
            notes.append(f"entry point removed: {n['entry']}")
        if n.get("old_signature"):
            notes.append(f"signature changed from `{n['old_signature']}`")
        if n.get("fields_added"):
            notes.append("new fields: " + ", ".join(f"`{f}`" for f in n["fields_added"][:6]))
        if n.get("fields_removed"):
            notes.append("removed fields: " + ", ".join(f"`{f}`" for f in n["fields_removed"][:6]))
        if ch == "removed":
            was = sorted({e["source"] for e in edges if e["target"] == n["id"] and e["type"] in ("calls", "creates", "maybe_calls")} - {n["id"]})
            if was:
                notes.append("was used by " + ", ".join(f"`{disp(c)}`" for c in was[:5]) + (" …" if len(was) > 5 else ""))
        groups = {}
        for e in added_out.get(n["id"], []):
            groups.setdefault(verbs_add[e["type"]], []).append(disp(e["target"]))
        if ch != "removed":
            for e in removed_out.get(n["id"], []):
                groups.setdefault(verbs_rm[e["type"]], []).append(disp(e["target"]))
        for verb, ts in groups.items():
            ts = list(dict.fromkeys(ts))
            more = f" and {len(ts) - 6} more" if len(ts) > 6 else ""
            notes.append(f"{verb} {', '.join(f'`{t}`' for t in ts[:6])}{more}")
        cs = sorted(callers.get(n["id"], set()) - {n["id"]})
        if ch == "changed" and cs:
            notes.append(f"used by {len(cs)} place{'s' if len(cs) != 1 else ''}: "
                         + ", ".join(f"`{disp(c)}`" for c in cs[:5]) + (" …" if len(cs) > 5 else ""))
        if ch == "added" and cs:
            notes.append("called from " + ", ".join(f"`{disp(c)}`" for c in cs[:5]) + (" …" if len(cs) > 5 else ""))
        if ch == "added" and not cs and not n.get("entry") and n["kind"] in ("function", "method"):
            notes.append("not called from inside the project (new public API, or unused)")
        n["notes"] = notes
        summary.append({"id": n["id"], "change": ch, "kind": n["kind"], "name": disp(n["id"]),
                        "file": n["file"], "line": n["line"], "entry": n.get("entry"), "notes": notes})

    order = {"added": 0, "changed": 1, "removed": 2}
    summary.sort(key=lambda s: (not (s["entry"] and s["change"] == "added"), order[s["change"]], s["file"], s["line"]))

    counts = {c: sum(1 for s in summary if s["change"] == c) for c in ("added", "changed", "removed")}
    counts["links_added"] = sum(1 for e in edges if e["change"] == "added" and e["type"] != "uses")
    counts["links_removed"] = sum(1 for e in edges if e["change"] == "removed" and e["type"] != "uses")
    counts["new_entries"] = sum(1 for s in summary if s["change"] == "added" and s["entry"])

    merged = dict(new)
    merged["nodes"], merged["edges"] = nodes, edges
    merged["diff"] = {"base": base_label, "head": head_label, "counts": counts, "summary": summary}
    return merged


# ------------------------------------------------------------------ reports
def terminal_summary(d: dict) -> str:
    c = d["counts"]
    if not d["summary"]:
        return f"No structural changes between {d['base']} and {d['head']}."
    lines = [f"Changes {d['base']} → {d['head']}: {c['added']} added, {c['changed']} changed, "
             f"{c['removed']} removed; {c['links_added']} new links, {c['links_removed']} removed links"]
    mark = {"added": "+", "changed": "~", "removed": "-"}
    for s in d["summary"][:40]:
        lines.append(f"  {mark[s['change']]} {s['name']}  ({s['file']}:{s['line']})")
        for note in s["notes"][:3]:
            lines.append(f"      {note.replace('`', '')}")
    if len(d["summary"]) > 40:
        lines.append(f"  … {len(d['summary']) - 40} more in the map")
    return "\n".join(lines)


def markdown_report(d: dict, map_note: str = "") -> str:
    c = d["counts"]
    out = [f"### repomap: what this change does structurally", "",
           f"`{d['base']}` → `{d['head']}`", ""]
    if not d["summary"]:
        out.append("No structural changes: no functions, classes or links were added, changed or removed.")
        return "\n".join(out) + "\n"
    out.append(f"**{c['added']}** added · **{c['changed']}** changed · **{c['removed']}** removed · "
               f"**{c['links_added']}** new links · **{c['links_removed']}** removed links")
    out.append("")
    entries = [s for s in d["summary"] if s["change"] == "added" and s["entry"]]
    if entries:
        out += ["#### New entry points", "These can be reached from outside the code (routes, pages, commands, scripts). "
                "Check they have the auth and validation they need.", ""]
        out += [f"- `{s['name']}`: {s['entry']} ({s['file']}:{s['line']})" for s in entries]
        out.append("")
    titles = {"added": "Added", "changed": "Changed", "removed": "Removed"}
    for ch in ("added", "changed", "removed"):
        items = [s for s in d["summary"] if s["change"] == ch and not (ch == "added" and s["entry"])]
        if not items:
            continue
        out += [f"#### {titles[ch]}", ""]
        for s in items[:60]:
            note = ("; ".join(s["notes"])) if s["notes"] else ""
            out.append(f"- `{s['name']}` ({s['file']}:{s['line']})" + (f": {note}" if note else ""))
        if len(items) > 60:
            out.append(f"- … and {len(items) - 60} more")
        out.append("")
    if map_note:
        out += [map_note, ""]
    return "\n".join(out)
