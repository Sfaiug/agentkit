package tick

import (
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// tellParked is the notice of a run the ladder parked as stalled that has not gone out
// (watch.tell_parked): typed into the seat that launched it, under the run's lock, and marked told.
// A notice Go does not type, to a run launched from no seat, a seat not up or not at its quiet
// prompt, or a line too long to type whole, is Python's card, page or summary, as it stood.
func (t *ticking) tellParked(dir string) error {
	return run.Change(dir, func(current *run.Object) error {
		if current.Str("state") != "stalled" || current.Truthy("stalled_notified") {
			return nil
		}
		step := "the run"
		if stalls := current.List("stalls"); len(stalls) > 0 {
			if last, _ := stalls[len(stalls)-1].(*run.Object); last != nil && last.Truthy("step") {
				step = run.Text(last.Get("step"))
			}
		}
		name, line := run.Seat(current), parkedLine(filepath.Base(dir), step)
		if !typable(name, line) || !seat.TypeAtPrompt(name, line, nil, func(*run.Object) error { return nil }, t.log.line) &&
			!t.cardParked(name, filepath.Base(dir), step, line) {
			return errLeft
		}
		current.Set("stalled_notified", true)
		return nil
	})
}

// parkedLine is what the seat that launched a parked run is told.
func parkedLine(id, step string) string {
	return fmt.Sprintf("run %s stalled three times at %s; parked: ak run resume %s", id, step, id)
}

// typable is whether Go may type that line into that seat: one up, and a line it types whole.
func typable(name, line string) bool {
	return name != "" && seat.Watching(name) && !config.TooLong(line)
}
