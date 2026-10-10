"""Checks that the demo project maps to the structure described in the video."""

from pathlib import Path

from codemap.analyzer import Analyzer

SHOP = Path(__file__).parent.parent / "examples" / "shop"


def graph():
    g = Analyzer(SHOP).analyze()
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = {(e["source"], e["target"], e["type"]) for e in g["edges"]}
    return nodes, edges


def test_symbol_kinds():
    nodes, _ = graph()
    assert nodes["main:main"]["entry"]
    assert nodes["main:__main__"]["kind"] == "entry"
    assert nodes["inventory:Inventory"]["kind"] == "class"
    for d in ("Product", "Order", "OrderItem", "OrderStatus"):
        assert nodes[f"models:{d}"]["kind"] == "data"
    assert nodes["models:OrderStatus"]["data_kind"] == "enum"
    assert nodes["inventory:Inventory.reserve"]["parent"] == "inventory:Inventory"


def test_storyline_edges():
    _, edges = graph()
    expected = {
        ("main:__main__", "main:main", "calls"),
        ("main:main", "main:validate_order", "calls"),
        ("main:main", "main:process_order", "calls"),
        ("main:main", "inventory:Inventory", "creates"),
        # resolved through the parameter annotation `inventory: Inventory`
        ("main:process_order", "inventory:Inventory.reserve", "calls"),
        ("main:process_order", "inventory:Inventory.restock", "calls"),
        ("main:process_order", "models:Order.total", "calls"),
        # composition, from dataclass field annotations
        ("models:Order", "models:OrderItem", "has"),
        ("models:Order", "models:OrderStatus", "has"),
        ("models:OrderItem", "models:Product", "has"),
        # direct references in a body
        ("inventory:Inventory.reserve", "models:OrderStatus", "uses"),
    }
    missing = expected - edges
    assert not missing, missing


def test_no_self_or_duplicate_edges():
    g = Analyzer(SHOP).analyze()
    keys = [(e["source"], e["target"], e["type"]) for e in g["edges"]]
    assert len(keys) == len(set(keys))
