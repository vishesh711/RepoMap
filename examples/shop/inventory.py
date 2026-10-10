from models import Order, OrderStatus, Product


class Inventory:
    def __init__(self, products: list[Product]):
        self.stock: dict[str, int] = {p.sku: 10 for p in products}

    def reserve(self, order: Order) -> bool:
        for item in order.items:
            if self.stock.get(item.product.sku, 0) < item.quantity:
                order.status = OrderStatus.REJECTED
                return False
        for item in order.items:
            self.stock[item.product.sku] -= item.quantity
        order.status = OrderStatus.RESERVED
        return True

    def restock(self, product: Product, amount: int) -> None:
        self.stock[product.sku] = self.stock.get(product.sku, 0) + amount
