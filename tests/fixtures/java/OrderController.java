package shop;

public class OrderController {
    private final Inventory inventory;
    public OrderController(Inventory inventory) { this.inventory = inventory; }

    @PostMapping("/orders")
    public String create(Order order) {
        if (!inventory.reserve(order)) { return "rejected"; }
        Receipt r = new Receipt(order);
        return r.summary();
    }
}
