package handback

import (
	"errors"
	"path/filepath"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

const looked = "read by its seat's own ak run status or ak wait: printed there, not typed"

// LookLine reads the tick's line and returns an action to record it after successful output.
// A contended look leaves both the full notice and the record to that delivery, even if its
// lock is released during output. No lock spans the output itself.
func LookLine(dir string, record *run.Object) (string, func()) {
	if !run.Waits(record) {
		return "", nil
	}
	held, err := lock.Try(filepath.Join(dir, "delivery.lock"))
	if err != nil && !errors.Is(err, lock.ErrHeld) {
		return "", nil
	}
	if held != nil {
		defer held.Close()
	}
	line := handbackLine(record, dir, held != nil, looksLive(record))
	if line == "" || held == nil {
		return line, nil
	}
	return line, func() { printedAtLook(dir, record) }
}

// printedAtLook records a line successfully printed by its seat. No lock spans the output,
// and a tick now holding the delivery lock finishes its delivery without waiting on the look.
func printedAtLook(dir string, snapshot *run.Object) {
	held, err := lock.Try(filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return
	}
	defer held.Close()
	said, _ := run.Read(dir)
	if said != nil && sameAttempt(snapshot, said) && run.Waits(said) {
		// the line printed was the snapshot's: health landing since leaves its live notice owed
		told := looksLive(snapshot) && run.Equal(snapshot.Get("live_at"), said.Get("live_at")) && !said.Truthy("live_typed")
		mark(dir, said, append([]any{"handed_back", now(), "reported", true,
			"handback_note", looked,
			"handback_pending", nil, "handback_wait_reason", nil, "notification_pending", nil},
			saidLive(told, "live_notified", now(), "live_note", looked)...)...)
	}
}

// looksLive is whether a look's line says its merge went live too: no line typed already says it.
func looksLive(record *run.Object) bool {
	return record.Truthy("merged") && record.Truthy("live_at") && !record.Truthy("live_typed")
}
