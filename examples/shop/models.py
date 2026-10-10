from dataclasses import dataclass, field
from enum import Enum


class OrderStatus(Enum):
    PENDING = "pending"
    RESERVED = "reserved"
    REJECTED = "rejected"


@dataclass
class Product:
    sku: str
    name: str
    price: float


@dataclass
class OrderItem:
    product: Product
    quantity: int


@dataclass
class Order:
    order_id: str
    items: list[OrderItem] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING

    def total(self) -> float:
        return sum(i.product.price * i.quantity for i in self.items)
