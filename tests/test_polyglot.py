"""Each fixture is the inventory example from the README, written in another language."""

from pathlib import Path

import pytest

from repomap.polyglot import Polyglot

FIX = Path(__file__).parent / "fixtures"


def graph(lang):
    g = Polyglot(FIX / lang).analyze()
    edges = {(e["source"], e["target"], e["type"]) for e in g["edges"]}
    nodes = {n["id"]: n for n in g["nodes"]}
    return nodes, edges


def test_typescript():
    nodes, edges = graph("ts")
    assert nodes["models.ts:OrderStatus"]["data_kind"] == "enum"
    assert nodes["inventory.ts:Inventory.reserve"]["parent"] == "inventory.ts:Inventory"
    route = next(n for n in nodes.values() if n["name"] == "POST /orders")
    assert route["entry"].startswith("HTTP route")
    assert {
        (route["id"], "inventory.ts:Inventory", "creates"),
        (route["id"], "server.ts:processOrder", "calls"),
        # resolved through the parameter type `inv: Inventory`
        ("server.ts:processOrder", "inventory.ts:Inventory.reserve", "calls"),
        ("server.ts:processOrder", "inventory.ts:Inventory.restock", "calls"),
        ("server.ts:processOrder", "models.ts:Order.total", "calls"),
        ("models.ts:Order", "models.ts:OrderItem", "has"),
        ("models.ts:OrderItem", "models.ts:Product", "has"),
    } <= edges


def test_go():
    nodes, edges = graph("go")
    assert nodes["shop.go:Inventory"]["kind"] == "class"       # struct with methods
    assert nodes["shop.go:Order"]["kind"] == "data"            # plain struct
    assert nodes["main.go:main"]["entry"] == "main() function"
    assert {
        ("main.go:main", "shop.go:NewInventory", "calls"),
        ("main.go:main", "main.go:Server", "creates"),
        # through the receiver `s *Server` and the field `inv *Inventory`
        ("main.go:Server.handleOrder", "shop.go:Inventory.Reserve", "calls"),
        ("shop.go:Inventory.Reserve", "shop.go:Inventory.check", "calls"),
        ("shop.go:Order", "shop.go:OrderItem", "has"),
    } <= edges
    route = next(n for n in nodes.values() if n["name"] == "ANY /orders")
    assert (route["id"], "main.go:Server.handleOrder", "calls") in edges


def test_java():
    nodes, edges = graph("java")
    create = "OrderController.java:OrderController.create"
    assert nodes[create]["entry"] == "HTTP route PostMapping /orders"
    assert {
        (create, "Inventory.java:Inventory.reserve", "calls"),  # implicit this.inventory field
        (create, "Inventory.java:Receipt", "creates"),
        (create, "Inventory.java:Receipt.summary", "calls"),    # local `Receipt r`
        ("Inventory.java:Inventory.reserve", "Inventory.java:BaseService.log", "calls"),  # inherited
        ("Inventory.java:Inventory", "Inventory.java:BaseService", "extends"),
    } <= edges


def test_rust():
    nodes, edges = graph("rust")
    assert nodes["main.rs:Inventory.reserve"]["parent"] == "main.rs:Inventory"
    assert {
        ("main.rs:main", "main.rs:Inventory.new", "calls"),
        ("main.rs:main", "main.rs:Order", "creates"),
        ("main.rs:main", "main.rs:Inventory.reserve", "calls"),   # `let mut inv = Inventory::new()`
        ("main.rs:Inventory.reserve", "main.rs:Inventory.check", "calls"),
        ("main.rs:Order", "main.rs:Item", "has"),
    } <= edges
