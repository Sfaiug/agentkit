package seat

import (
	"errors"
	"io/fs"
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

// legacySeats adds to bare the seats of old on the default server, the person's own: what carries
// ak's mark there under a name ak's own server holds no seat by (orch.sessions).  False where one is
// a record's, whose screen would be read on the default server, which Go does not.
func legacySeats(names, ours []string, bare map[string]string) bool {
	for _, session := range tmux.Sessions(tmux.Default) {
		if _, own := bare[session.Name]; session.Mark != "1" || own || slices.Contains(ours, session.Name) {
			continue
		}
		if slices.Contains(names, session.Name) {
			return false
		}
		bare[session.Name] = tmux.Default
	}
	return true
}

// unbared is whether Go reads every bare seat by its name: each a seat's name, and a pane of each
// still running, as one whose panes have all died is read by what its record says.
func unbared(bare map[string]string) bool {
	dead := map[string][]string{}
	for name, server := range bare {
		if _, asked := dead[server]; !asked {
			dead[server] = tmux.Dead(server)
		}
		if config.SessionName(name) != name || slices.Contains(dead[server], name) {
			return false
		}
	}
	return true
}

// bareSeat is the row of a bare seat on that server, its word decided from its files and runs as
// a look at a screen nobody reads would decide it; false where Go does not read its seat file.
func bareSeat(state, name, server string, mine []ran, now time.Time) (Seat, bool) {
	started, err := tmux.Ask(server, "display-message", "-p", "-t", "="+name+":", "#{session_created}")
	file, unread := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	if err != nil || unread != nil && !errors.Is(unread, fs.ErrNotExist) ||
		unread == nil && (file == nil || !only(file, slices.Concat(seatFields, lookFields)) || file.Truthy("stopped_at") || file.Truthy("closed_by_owner")) {
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
// save and close where no record keeps any seat (orch.sweep_finished).
func strangers() bool { return slices.ContainsFunc(tmux.Sessions(tmux.Own()), unrecorded) }
