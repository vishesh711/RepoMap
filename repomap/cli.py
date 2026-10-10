"""
repomap: turn a codebase into an interactive storyline map.

    repomap path/to/project                  # a folder on your machine
    repomap https://github.com/owner/repo    # any public GitHub repo (cloned for you)
    repomap owner/repo --branch dev -o map.html

    repomap --diff main                      # what changed vs main (uncommitted edits included)
    repomap --diff HEAD                      # just the edits you haven't committed yet
    repomap --diff v1.2 --head v1.3 --report changes.md

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

from .diff import compare, git as diff_git, markdown_report, resolve_ref, snapshot, terminal_summary
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


def clone(target: str, branch: str | None, full: bool = False) -> tuple[Path, dict]:
    m = GITHUB_RE.match(target)
    if not m:
        raise SystemExit(f"Not a GitHub repo: {target}")
    slug = f"{m['owner']}/{m['repo']}"
    ref = branch or m["ref"]
    dest = Path(tempfile.mkdtemp(prefix="repomap-")) / m["repo"]
    depth = ["--filter=blob:none"] if full else ["--depth", "1"]  # diffs need history
    cmd = ["clone", *depth, "--quiet"] + (["--branch", ref] if ref else []) + \
          [f"https://github.com/{slug}.git", str(dest)]
    print(f"Cloning {slug}{' @ ' + ref if ref else ''} ...", file=sys.stderr)
    r = _git(cmd)
    if r.returncode != 0:
        raise SystemExit(f"Couldn't clone {slug}: {r.stderr.strip() or 'git failed'}\n"
                         "Check the name, or clone it yourself and pass the folder (private repos need your git login).")
    sha = _git(["rev-parse", "HEAD"], cwd=dest).stdout.strip()
    return dest, {"web": f"https://github.com/{slug}", "slug": slug, "sha": sha, "ref": ref}


def main(argv=None):
    p = argparse.ArgumentParser(prog="repomap", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("target", nargs="?", default=".",
                   help="folder, GitHub URL, or owner/repo (default: current folder)")
    p.add_argument("-o", "--out", help="HTML file to write (default: repomap.html, or repomap-diff.html with --diff)")
    p.add_argument("--json", metavar="FILE", help="also write the raw graph as JSON")
    p.add_argument("--branch", help="branch or tag to map when cloning")
    p.add_argument("--subdir", help="only map this folder inside the repo")
    p.add_argument("--include-tests", action="store_true", help="include test files and test folders")
    p.add_argument("--title", help="page title (default: '<name> code map')")
    p.add_argument("--keep-clone", action="store_true", help="don't delete the cloned repo afterwards")
    g = p.add_argument_group("diff mode")
    g.add_argument("--diff", metavar="BASE", help="show what changed since BASE (branch, tag, commit, HEAD~1, ...)")
    g.add_argument("--head", metavar="REF", help="compare BASE with this ref instead of the folder as it is now")
    g.add_argument("--report", metavar="FILE", help="also write the change summary as Markdown (e.g. for a PR comment)")
    args = p.parse_args(argv)
    if args.head and not args.diff:
        p.error("--head needs --diff BASE")
    if args.report and not args.diff:
        p.error("--report needs --diff BASE")
    args.out = args.out or ("repomap-diff.html" if args.diff else "repomap.html")

    t0 = time.perf_counter()
    cloned = None
    target = args.target
    local = Path(target)
    if local.is_dir():
        root, repo = local, repo_info(local)
    elif GITHUB_RE.match(target) and not local.exists():
        root, repo = clone(target, args.branch, full=bool(args.diff))
        cloned = root.parent
    else:
        p.error(f"{target} is not a folder or a GitHub repo")

    if args.subdir:
        root = root / args.subdir
        if not root.is_dir():
            p.error(f"{args.subdir} is not a folder in {target}")
        if repo:
            repo = {**repo, "subdir": "/".join(x for x in (repo.get("subdir"), args.subdir.strip("/")) if x)}

    temp_dirs = []
    try:
        if args.diff:
            graph = run_diff(root, args, repo, temp_dirs)
        else:
            graph = scan(root, include_tests=args.include_tests)
    finally:
        for d in temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
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

    if args.report:
        Path(args.report).write_text(markdown_report(graph["diff"]), encoding="utf-8")
    if args.diff:
        print(terminal_summary(graph["diff"]))
        if args.report:
            print(f"Report {Path(args.report).resolve()}")
        print(f"Open {out.resolve()}")
        return 0

    langs = ", ".join(f"{k} {v['files']}" for k, v in graph["languages"].items())
    print(f"Mapped {s['files']} files ({langs}), {s['lines']:,} lines in {time.perf_counter() - t0:.1f}s: "
          f"{s['functions'] + s['methods']} functions/methods, {s['classes']} classes, "
          f"{s['data']} data types, {s['entries']} entry points, {s['edges']} links")
    for w in graph["warnings"][:5]:
        print("  note:", w, file=sys.stderr)
    print(f"Open {out.resolve()}")
    return 0


def run_diff(root: Path, args, repo: dict | None, temp_dirs: list) -> dict:
    """Scan BASE and HEAD (or the working folder) and compare them."""
    code, top, _ = diff_git(["rev-parse", "--show-toplevel"], root)
    if code != 0:
        raise SystemExit(f"{root} isn't inside a git repository, so there's nothing to compare against.")
    top = Path(top.strip())
    sub = root.resolve().relative_to(top.resolve()).as_posix()
    sub = "" if sub == "." else sub

    def keep(snap):
        temp_dirs.append(snap if not sub else snap.parents[len(Path(sub).parts) - 1])
        return snap

    base_sha, base_label = resolve_ref(top, args.diff)
    base_root = keep(snapshot(top, base_sha, sub))
    if args.head:
        head_sha, head_label = resolve_ref(top, args.head)
        head_root = keep(snapshot(top, head_sha, sub))
    else:
        head_root = root
        dirty = diff_git(["status", "--porcelain", "--", "."], root)[1].strip()
        head_label = "working folder" + (" (with uncommitted changes)" if dirty else "")
    print(f"Comparing {base_label} → {head_label} ...", file=sys.stderr)
    old = scan(base_root, include_tests=args.include_tests)
    new = scan(head_root, include_tests=args.include_tests)
    merged = compare(old, new, base_root, head_root, base_label, head_label, base_sha)
    if args.head and repo:
        repo["sha"] = head_sha
    return merged


if __name__ == "__main__":
    sys.exit(main())
