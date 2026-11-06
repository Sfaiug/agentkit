package tick

import (
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// noneParked is whether every run the tick parked as stalled has had its notice.
func noneParked() bool {
	return run.Every(func(_ string, record *run.Object) bool {
		return record.Str("state") != "stalled" || record.Truthy("stalled_notified")
	})
}

// tellParked is the stall recovery row's notice of a run it parked as stalled that has not gone
// out (watch.tell_parked): typed into the seat that launched it, under the run's lock, and marked
// told.  A notice Go does not type, to a run launched from no seat, a seat not up or not at its
// quiet prompt, or a line too long to type whole, is Python's card, page or summary, as it stood.
func (t *ticking) tellParked() error {
	var parked []string
	if !run.Every(func(dir string, record *run.Object) bool {
		if record.Str("state") == "stalled" && !record.Truthy("stalled_notified") {
			parked = append(parked, dir)
		}
		return true
	}) {
		return errLeft
	}
	for _, dir := range parked {
		err := run.Change(dir, func(current *run.Object) error {
			if current.Str("state") != "stalled" || current.Truthy("stalled_notified") {
				return nil
			}
			id, step := filepath.Base(dir), "the run"
			if stalls := current.List("stalls"); len(stalls) > 0 {
				if last, _ := stalls[len(stalls)-1].(*run.Object); last != nil && last.Truthy("step") {
					step = run.Text(last.Get("step"))
				}
			}
			name, line := run.Seat(current), fmt.Sprintf("run %s stalled three times at %s; parked: ak run resume %s", id, step, id)
			if name == "" || !seat.Watching(name) || config.TooLong(line) ||
				!seat.TypeAtPrompt(name, line, nil, func(*run.Object) error { return nil }, t.log.line) {
				return errLeft
			}
			current.Set("stalled_notified", true)
			return nil
		})
		if err != nil {
			return err
		}
	}
	return nil
}
