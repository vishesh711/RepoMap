package shop;
public class Inventory extends BaseService {
    public boolean reserve(Order order) { log("reserve"); return true; }
}
class BaseService { protected void log(String m) {} }
class Order {}
class Receipt { Receipt(Order o) {} String summary() { return "ok"; } }
