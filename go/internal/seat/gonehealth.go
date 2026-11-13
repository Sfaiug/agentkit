package seat

import (
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// These remain after a harness dies or its seat is gone; none is a screen to read for its word, and
// its last turn's start (`stop`) is read only of a seat its panes run on.
func goneKind(kind, suffix string) bool {
	return suffix == "json" && slices.Contains([]string{"hook", "title", "card", "stop"}, kind) ||
		kind == ".hook" && suffix == "lock" || kind == "input" && suffix == "jsonl" || kind == "rulebook" && suffix == "md"
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

// healthGone publishes an absent seat under Health's announce lock, with no screen read.
// What its death cut off is the recovery rows' to judge later.
func (home Home) healthGone(state, name string, now time.Time) (bool, error) {
	at := slices.IndexFunc(home.Seats, func(seat Seat) bool { return seat.Name == name })
	if at < 0 || home.Seats[at].live {
		return false, nil
	}
	seat := home.Seats[at]
	return true, seat.announced(state, now, home.models)
}

// StampGone starts an absent record's retention clock once, as orch.stamp does. Live records
// are stamped by the tick; dead panes start their exit clock without winding seen.
func (home Home) StampGone(now time.Time) error {
	state := filepath.Join(config.Home(), "state")
	for _, seat := range home.records {
		if seat.live {
			continue
		}
		if seat.held {
			if err := stampExited(seat.Name, now); err != nil {
				return err
			}
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
