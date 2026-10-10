"""
codemap: turn a codebase into an interactive storyline map.

    codemap path/to/project                  # a folder on your machine
    codemap https://github.com/owner/repo    # any public GitHub repo (cloned for you)
    codemap owner/repo --branch dev -o map.html

Python, JavaScript, TypeScript, Go, Java, C#, Rust, C, C++, Ruby and PHP.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .render import render_html
from .scan import scan

GITHUB_RE = re.compile(r"^(?:https?://github\.com/|git@github\.com:|github\.com/)?"
                       r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?(?:/tree/(?P<ref>[^\s]+))?$")


def _git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def repo_info(folder: Path) -> dict | None:
    """GitHub web URL + commit for a local git checkout, if it has a GitHub remote."""
    if _git(["rev-parse", "--is-inside-work-tree"], cwd=folder).returncode != 0:
        return None
    sha = _git(["rev-parse", "HEAD"], cwd=folder).stdout.strip()
    remote = _git(["remote", "get-url", "origin"], cwd=folder).stdout.strip()
    top = _git(["rev-parse", "--show-toplevel"], cwd=folder).stdout.strip()
    m = GITHUB_RE.match(remote) if remote else None
    if not m:
        return {"sha": sha} if sha else None
    slug = f"{m['owner']}/{m['repo']}"
    info = {"web": f"https://github.com/{slug}", "slug": slug, "sha": sha}
    # When mapping a subfolder, links need the path from the repo root.
    try:
        sub = folder.resolve().relative_to(Path(top).resolve()).as_posix()
    except ValueError:
        sub = ""
    if sub and sub != ".":
        info["subdir"] = sub
    return info


def clone(target: str, branch: str | None) -> tuple[Path, dict]:
    m = GITHUB_RE.match(target)
    if not m:
        raise SystemExit(f"Not a GitHub repo: {target}")
    slug = f"{m['owner']}/{m['repo']}"
    ref = branch or m["ref"]
    dest = Path(tempfile.mkdtemp(prefix="codemap-")) / m["repo"]
    cmd = ["clone", "--depth", "1", "--quiet"] + (["--branch", ref] if ref else []) + \
          [f"https://github.com/{slug}.git", str(dest)]
    print(f"Cloning {slug}{' @ ' + ref if ref else ''} ...", file=sys.stderr)
    r = _git(cmd)
    if r.returncode != 0:
        raise SystemExit(f"Couldn't clone {slug}: {r.stderr.strip() or 'git failed'}\n"
                         "Check the name, or clone it yourself and pass the folder (private repos need your git login).")
    sha = _git(["rev-parse", "HEAD"], cwd=dest).stdout.strip()
    return dest, {"web": f"https://github.com/{slug}", "slug": slug, "sha": sha, "ref": ref}


def main(argv=None):
    p = argparse.ArgumentParser(prog="codemap", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("target", nargs="?", default=".",
                   help="folder, GitHub URL, or owner/repo (default: current folder)")
    p.add_argument("-o", "--out", default="codemap.html", help="HTML file to write (default: codemap.html)")
    p.add_argument("--json", metavar="FILE", help="also write the raw graph as JSON")
    p.add_argument("--branch", help="branch or tag to map when cloning")
    p.add_argument("--subdir", help="only map this folder inside the repo")
    p.add_argument("--include-tests", action="store_true", help="include test files and test folders")
    p.add_argument("--title", help="page title (default: '<name> code map')")
    p.add_argument("--keep-clone", action="store_true", help="don't delete the cloned repo afterwards")
    args = p.parse_args(argv)

    t0 = time.perf_counter()
    cloned = None
    target = args.target
    local = Path(target)
    if local.is_dir():
        root, repo = local, repo_info(local)
    elif GITHUB_RE.match(target) and not local.exists():
        root, repo = clone(target, args.branch)
        cloned = root.parent
    else:
        p.error(f"{target} is not a folder or a GitHub repo")

    if args.subdir:
        root = root / args.subdir
        if not root.is_dir():
            p.error(f"{args.subdir} is not a folder in {target}")
        if repo:
            repo = {**repo, "subdir": "/".join(x for x in (repo.get("subdir"), args.subdir.strip("/")) if x)}

    try:
        graph = scan(root, include_tests=args.include_tests)
    finally:
        if cloned and not args.keep_clone:
            shutil.rmtree(cloned, ignore_errors=True)
        elif cloned:
            print(f"Clone kept at {root}", file=sys.stderr)

    if repo:
        if repo.get("subdir"):  # make file paths relative to the repo root for GitHub links
            prefix = repo["subdir"].rstrip("/") + "/"
            for n in graph["nodes"]:
                n["repo_path"] = prefix + n["file"]
        graph["repo"] = repo
        graph["root"] = repo.get("slug", graph["root"])

    s = graph["stats"]
    if not graph["nodes"]:
        print(f"No functions or classes found in {target}. "
              "Supported: Python, JS/TS, Go, Java, C#, Rust, C/C++, Ruby, PHP.", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(graph, args.title), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(graph, indent=2), encoding="utf-8")

    langs = ", ".join(f"{k} {v['files']}" for k, v in graph["languages"].items())
    print(f"Mapped {s['files']} files ({langs}), {s['lines']:,} lines in {time.perf_counter() - t0:.1f}s: "
          f"{s['functions'] + s['methods']} functions/methods, {s['classes']} classes, "
          f"{s['data']} data types, {s['entries']} entry points, {s['edges']} links")
    for w in graph["warnings"][:5]:
        print("  note:", w, file=sys.stderr)
    print(f"Open {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
