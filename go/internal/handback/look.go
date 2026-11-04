package handback

import (
	"errors"
	"path/filepath"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// Waiting is an ending deferred to its seat's prompt, with no line already in its composer.
func Waiting(record *run.Object) bool {
	return record.Truthy("handback_pending") && !record.Truthy("handback_typed") && !handedBack(record)
}

// LookLine reads the tick's line without waiting on a delivery in progress. That delivery
// saves a compact line's full notice itself; only a look holding its lock may save one here.
func LookLine(dir string, record *run.Object) string {
	if !Waiting(record) {
		return ""
	}
	held, err := lock.Try(filepath.Join(dir, "delivery.lock"))
	if err != nil && !errors.Is(err, lock.ErrHeld) {
		return ""
	}
	if held != nil {
		defer held.Close()
	}
	return handbackLine(record, dir, held != nil)
}

// PrintedAtLook records a line successfully printed by its seat. No lock spans the output,
// and a tick now holding the delivery lock finishes its delivery without waiting on the look.
func PrintedAtLook(dir string, snapshot *run.Object) {
	held, err := lock.Try(filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return
	}
	defer held.Close()
	said, _ := run.Read(dir)
	if said != nil && sameAttempt(snapshot, said) && Waiting(said) {
		mark(dir, said, "handed_back", now(), "reported", true,
			"handback_note", "read by its seat's own ak run status or ak wait: printed there, not typed",
			"handback_pending", nil, "handback_wait_reason", nil, "notification_pending", nil)
	}
}
