"""Diff mode on a real git repo: commit the shop example, edit it like an AI would, compare."""

import shutil
import subprocess
from pathlib import Path

import pytest

from repomap import diff
from repomap.cli import main
from repomap.scan import scan

SHOP = Path(__file__).parent.parent / "examples" / "shop"


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "shop"
    shutil.copytree(SHOP, root)
    git("init", "-q", "-b", "main", cwd=root)
    git("add", "-A", cwd=root)
    git("commit", "-qm", "base", cwd=root)

    main_py = root / "main.py"
    s = main_py.read_text()
    s = s.replace('''def validate_order(order: Order) -> bool:
    return len(order.items) > 0 and all(i.quantity > 0 for i in order.items)


''', "")
    s = s.replace("        inventory.restock(order.items[0].product, 5)\n", "        notify_backorder(order)\n")
    s = s.replace("    if validate_order(order):\n        print(process_order(order, inventory))",
                  "    print(process_order(order, inventory))")
    s += '''

def notify_backorder(order: Order) -> None:
    print("backorder", order.order_id)
'''
    main_py.write_text(s)
    models = root / "models.py"
    models.write_text(models.read_text().replace('    REJECTED = "rejected"\n',
                                                 '    REJECTED = "rejected"\n    BACKORDERED = "backordered"\n'))
    # Pure reformatting must not count as a change.
    inv = root / "inventory.py"
    inv.write_text(inv.read_text().replace("    def restock(self, product: Product, amount: int) -> None:",
                                           "    def restock(self,  product: Product,  amount: int) -> None:"))
    return root


def changes(root, base="main"):
    sha, label = diff.resolve_ref(root, base)
    snap = diff.snapshot(root, sha)
    try:
        return diff.compare(scan(snap), scan(root), snap, root, label, "working folder", sha)
    finally:
        shutil.rmtree(snap, ignore_errors=True)


def test_statuses(repo):
    g = changes(repo)
    by = {n["id"]: n.get("change") for n in g["nodes"]}
    assert by["main:notify_backorder"] == "added"
    assert by["main:process_order"] == "changed"
    assert by["main:main"] == "changed"
    assert by["models:OrderStatus"] == "changed"
    assert by["removed:main:validate_order"] == "removed"
    assert by["inventory:Inventory.restock"] == "unchanged"   # whitespace only
    assert by["inventory:Inventory"] == "unchanged"           # members changed, not the class itself
    c = g["diff"]["counts"]
    assert (c["added"], c["changed"], c["removed"]) == (1, 3, 1)


def test_links_and_notes(repo):
    g = changes(repo)
    edges = {(e["source"], e["target"], e["type"]): e["change"] for e in g["edges"]}
    assert edges[("main:process_order", "main:notify_backorder", "calls")] == "added"
    assert edges[("main:process_order", "inventory:Inventory.restock", "calls")] == "removed"
    assert edges[("main:main", "removed:main:validate_order", "calls")] == "removed"
    notes = {s["id"]: " | ".join(s["notes"]) for s in g["diff"]["summary"]}
    assert "now calls `notify_backorder()`" in notes["main:process_order"]
    assert "no longer calls `Inventory.restock()`" in notes["main:process_order"]
    assert "new fields: `BACKORDERED`" in notes["models:OrderStatus"]
    assert "was used by `main()`" in notes["removed:main:validate_order"]
    proc = next(n for n in g["nodes"] if n["id"] == "main:process_order")
    assert "+        notify_backorder(order)" in proc["diff"]


def test_cli_report(repo, tmp_path, capsys):
    out, report = tmp_path / "d.html", tmp_path / "r.md"
    assert main([str(repo), "--diff", "main", "-o", str(out), "--report", str(report)]) == 0
    md = report.read_text()
    assert "**1** added · **3** changed · **1** removed" in md
    assert "`notify_backorder()`" in md
    assert "G.diff" in out.read_text() or '"diff":' in out.read_text()


def test_no_changes(repo):
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "edits", cwd=repo)
    g = changes(repo, "HEAD")
    assert g["diff"]["summary"] == []
    assert "No structural changes" in diff.terminal_summary(g["diff"])


def test_bad_ref(repo):
    with pytest.raises(SystemExit, match="Can't find"):
        diff.resolve_ref(repo, "no-such-branch")
