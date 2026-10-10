struct Order { items: Vec<Item> }
struct Item { qty: u32 }
struct Inventory { count: u32 }

impl Inventory {
    fn new() -> Self { Inventory { count: 0 } }
    fn reserve(&mut self, order: &Order) -> bool { self.check(order) }
    fn check(&self, order: &Order) -> bool { !order.items.is_empty() }
}

fn main() {
    let mut inv = Inventory::new();
    let order = Order { items: vec![] };
    inv.reserve(&order);
}
