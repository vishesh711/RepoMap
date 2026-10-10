package shop

import "net/http"

type Server struct { inv *Inventory }

func (s *Server) handleOrder(w http.ResponseWriter, r *http.Request) {
	o := &Order{}
	s.inv.Reserve(o)
}

func main() {
	s := &Server{inv: NewInventory()}
	http.HandleFunc("/orders", s.handleOrder)
}
