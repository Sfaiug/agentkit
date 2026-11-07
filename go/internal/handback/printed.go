package handback

import (
	"context"
	"path/filepath"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

const printedNote = "refused at launch: printed where it was asked, not typed"

// PrintedAtLaunch records the ending of a launch refused by the `ak run` its seat typed as handed
// back, Python's printed_at_launch: that command printed the refusal where the seat reads it, so
// typed in as well it would open a turn for news the seat already read.  Marked under the run's
// delivery lock, as Python's mark_delivery is, so no delivery under way lands between.
func PrintedAtLaunch(dir string, say func(string)) error {
	record, err := run.Read(dir)
	if record == nil || run.Seat(record) == "" {
		return err
	}
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	if mark(dir, record, "handed_back", now(), "reported", true, "handback_note", printedNote, "handback_pending", nil,
		"handback_typed", nil, "handback_wait_reason", nil, "notification_pending", nil) {
		say("run " + filepath.Base(dir) + " " + printedNote)
	}
	return nil
}
