package seat

import (
	"path/filepath"
	"slices"
	"time"

	"agentkit/internal/config"
)

// Explain is Python's orch.explain of the seat by that name, once its listing has written into
// the records what it reconciles and infers and its announce the seat's word: the word, why, and
// what read its screen, or that nothing did where its process is gone; false where no seat Go reads
// goes by that name.
func (home Home) Explain(name string, now time.Time) ([]string, bool, error) {
	state := filepath.Join(config.Home(), "state")
	at := slices.IndexFunc(home.Seats, func(seat Seat) bool { return seat.Name == name })
	if at >= 0 && home.Seats[at].live {
		lines, err := explainLive(state, name, home.runs, home.readers)
		if err == nil {
			err = reconcile(state, home.records, true)
		}
		return lines, true, err
	}
	if err := reconcile(state, home.records, true); err != nil {
		return nil, false, err
	}
	if at < 0 {
		return nil, false, nil
	}
	seat := home.Seats[at]
	if err := seat.announce(state, now, home.models); err != nil {
		return nil, false, err
	}
	return seat.Explanation(now), true, nil
}
