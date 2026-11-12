package seat

import "slices"

// dead is the seat as Health asks ok of it once tmux holds it with all its panes dead, before it is
// published gone: who it is and its harness, no screen (orch.sessions' `exited`).
func (seat Seat) dead() Live { return Live{Name: seat.Name, Own: seat.own, Exited: true} }

// deadOK is whether Health may publish the seat gone, read as no seat its panes run on: ok asked of
// it where tmux holds it with all its panes dead (dead).  One tmux no longer holds, which
// watch.health never reaches, is not asked.
func (home Home) deadOK(name string, ok func(Live) bool) bool {
	at := slices.IndexFunc(home.Seats, func(seat Seat) bool { return seat.Name == name })
	return at < 0 || !home.Seats[at].held || ok(home.Seats[at].dead())
}
