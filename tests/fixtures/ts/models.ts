export enum OrderStatus { Pending = "pending", Reserved = "reserved" }
export interface Product { sku: string; price: number }
export interface OrderItem { product: Product; quantity: number }
export class Order {
  items: OrderItem[] = [];
  status: OrderStatus = OrderStatus.Pending;
  total(): number { return this.items.reduce((s, i) => s + i.product.price * i.quantity, 0); }
}
