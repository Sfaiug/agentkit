package seat

import (
	"path/filepath"
	"slices"
	"strconv"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// A bare seat is one tmux holds under a name no record keeps (orch.server_sessions): opened by
// hand on ak's own server, or before ak had a server of its own on the person's default one, where
// it is `legacy`.  Nothing names the harness it runs (watch.seat_model), so nothing reads its
// screen and no pass types into it: its row names no models and no project, tmux's start dates it,
// and its word is what its files and runs say.

// bareSeat is the row of a bare seat on that server, its word decided from its files and runs as
// a look at a screen nobody reads would decide it; false where its seat file holds what Go does not
// read there: the owner's stop, or a question kept back, which no look at it ever asks.
func bareSeat(state, name, server string, mine []ran, now time.Time) (Seat, bool) {
	started, err := tmux.Ask(server, "display-message", "-p", "-t", "="+name+":", "#{session_created}")
	if file, known := seatRead(state, name); err != nil || !known || !bareFile(file) {
		return Seat{}, false
	}
	created, err := strconv.Atoi(started)
	if err != nil {
		created = int(now.Unix())
	}
	seat := Seat{Name: name, Project: "no project", Tally: tally(mine, now), Orchestrator: "?", Workers: "?", Created: float64(created),
		live: true, legacy: server == tmux.Default, mine: mine}
	if seat.decided(state, sight{}, seconds(now), false) != nil {
		return Seat{}, false
	}
	return seat, true
}

// bareFile is whether a bare seat's file, nil for none, holds nothing Go leaves to Python there.
func bareFile(file *run.Object) bool {
	return file == nil || !file.Truthy("stopped_at") && !file.Truthy("closed_by_owner") && file.Get("unasked") == nil
}

// server is the tmux server holding the seat (orch.seat_socket): ak's own, or the default one for a
// legacy seat.
func (seat Seat) server() string {
	if seat.legacy {
		return tmux.Default
	}
	return tmux.Own()
}

// Legacy is whether the seat lives on the person's default tmux server, from before ak had its own.
func (seat Seat) Legacy() bool { return seat.legacy }

// looked is whether ak reads the seat's screen: a pane of its session runs on, and its record names
// the harness it runs (watch.look_at).
func (seat Seat) looked() bool { return seat.live && seat.own != "" }

// strangers is whether ak's server holds a session that is no seat, which Python's maintenance may
// save and close (orch.sweep_finished).
func strangers() bool {
	held, seats := holdings(filepath.Join(config.Home(), "state"))
	return slices.ContainsFunc(held, func(name string) bool { return seats[name] != tmux.Own() })
}
