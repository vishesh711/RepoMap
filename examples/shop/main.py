from inventory import Inventory
from models import Order, OrderItem, Product

CATALOG = [Product("A1", "Keyboard", 49.0), Product("B2", "Mouse", 19.0)]


def validate_order(order: Order) -> bool:
    return len(order.items) > 0 and all(i.quantity > 0 for i in order.items)


def process_order(order: Order, inventory: Inventory) -> str:
    if not inventory.reserve(order):
        inventory.restock(order.items[0].product, 5)
        return "backordered"
    return f"reserved, total ${order.total():.2f}"


def main():
    inventory = Inventory(CATALOG)
    order = Order("o-1", [OrderItem(CATALOG[0], 2)])
    if validate_order(order):
        print(process_order(order, inventory))


if __name__ == "__main__":
    main()
