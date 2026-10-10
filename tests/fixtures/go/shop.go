package shop

type Product struct { SKU string; Price float64 }
type OrderItem struct { Product Product; Quantity int }
type Order struct { Items []OrderItem }

type Inventory struct { stock map[string]int }

func NewInventory() *Inventory { return &Inventory{stock: map[string]int{}} }

func (inv *Inventory) Reserve(o *Order) bool { return inv.check(o) }
func (inv *Inventory) check(o *Order) bool { return len(o.Items) > 0 }
