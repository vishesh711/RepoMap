import { Order, OrderStatus, Product } from "./models";
export class Inventory {
  private stock = new Map<string, number>();
  constructor(products: Product[]) { products.forEach(p => this.stock.set(p.sku, 10)); }
  reserve(order: Order): boolean { order.status = OrderStatus.Reserved; return true; }
  restock(product: Product, n: number) { this.stock.set(product.sku, n); }
}
