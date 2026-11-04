package seat

import (
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/hookfact"
	"agentkit/internal/lifecycle"
	"agentkit/internal/run"
)

// These remain after a harness dies; none is a screen to read for its word.
func goneKind(kind, suffix string) bool {
	return suffix == "json" && slices.Contains([]string{"hook", "title", "card"}, kind) ||
		kind == ".hook" && suffix == "lock" || kind == "input" && suffix == "jsonl"
}

// RestingGone leaves revival and the line it owes to Python: a past screen or a newer hook may
// hold a turn or background work even where the gone seat's plan owes nothing.
func (home Home) RestingGone() bool {
	for _, seat := range home.Seats {
		if seat.live || seat.closed {
			continue
		}
		if seat.held || seat.Word == "needs you" && !seat.waitingQuestion() || seat.Word == "working" {
			return false
		}
		file, _ := run.ReadJSON(seatFile(seat.Name))
		if file == nil {
			file = run.NewObject()
		}
		fact := hookfact.Standing(seat.Name)
		hooked, event, err := lifecycle.State(seat.own, fact)
		found := sight{state: file.Str("state"), rule: file.Str("rule"), hooked: file.Str("hooked"), hookedEvent: file.Str("hooked_event")}
		if hooked != "" && fact.At != 0 && fact.At != at(file.Get("hooked_at")) {
			found = sight{state: hooked, hooked: hooked, hookedEvent: event}
		}
		flight, _ := found.turnInFlight(seat.own)
		if err != nil || found.state == "asking" || flight || len(fact.Holds) > 0 || file.Truthy("holds") || file.Truthy("reopened_at") {
			return false
		}
	}
	return true
}

// Repositories includes absent records: their projects still take part in the tick's reads.
func (home Home) Repositories() []string {
	var repos []string
	for _, seat := range home.records {
		if repo, _ := seat.repo.(string); repo != "" && !slices.Contains(repos, repo) {
			repos = append(repos, repo)
		}
	}
	return repos
}

// healthGone publishes a resting absent seat under Health's announce lock, with no screen read.
func (home Home) healthGone(state, name string, now time.Time) (bool, error) {
	at := slices.IndexFunc(home.Seats, func(seat Seat) bool { return seat.Name == name })
	if at < 0 || home.Seats[at].live || home.Seats[at].held || !home.RestingGone() {
		return false, nil
	}
	seat := home.Seats[at]
	return true, seat.announced(state, now, home.models)
}

// StampGone starts an absent record's retention clock once, as orch.stamp does. Live records
// are stamped by the tick; held panes still leave it to Python.
func (home Home) StampGone(now time.Time) error {
	state := filepath.Join(config.Home(), "state")
	for _, seat := range home.records {
		if seat.live || seat.held {
			continue
		}
		if err := update(state, seat.Name, func(record *run.Object) bool {
			if record.Truthy("seen") {
				return false
			}
			record.Set("seen", run.Float(float64(now.Unix())))
			return true
		}); err != nil {
			return err
		}
	}
	return nil
}

// WaitsOnNothing includes every record, as watch.wait_over does: an absent seat's completed
// wait still owes its line, and an owner-closed seat's wait still has to end on its fact.
func (home Home) WaitsOnNothing() bool {
	for _, seat := range home.records {
		file, _ := run.ReadJSON(seatFile(seat.Name))
		if file == nil {
			continue
		}
		wait := file.Dict("wait")
		if wait == nil {
			continue
		}
		_, named := wait.Get("on").(string)
		if named && !wait.Truthy("told") {
			return false
		}
	}
	return true
}

// Retained is whether no record is due for Python's sweep, using the menu's retention rule.
func (home Home) Retained(now time.Time) bool {
	state := filepath.Join(config.Home(), "state")
	return !slices.ContainsFunc(home.records, func(seat Seat) bool { return seat.retired(state, now) })
}
