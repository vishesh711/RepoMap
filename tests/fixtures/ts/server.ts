import express from "express";
import { Inventory } from "./inventory";
import { Order } from "./models";
const app = express();
function processOrder(order: Order, inv: Inventory) {
  if (!inv.reserve(order)) inv.restock(order.items[0].product, 5);
  return order.total();
}
app.post("/orders", (req, res) => {
  const inv = new Inventory([]);
  res.json(processOrder(new Order(), inv));
});
app.listen(3000);
