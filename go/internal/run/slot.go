package run

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/config"
)

// SlotNote is Python's gate.slot_note, the line under a queued run, false where Go does not read
// it: a slot queue a poll left (runs/.slots.queue), a reason that is no text, another run waiting
// for a slot whose order against this one is gate.slot_counts', or a full count that asks whether
// the run goes first as an install's fix (update.first_place).
func SlotNote(record *Object) (string, bool) {
	if _, err := os.Lstat(filepath.Join(Runs(), ".slots.queue")); !errors.Is(err, fs.ErrNotExist) {
		return "", false
	}
	if record.Truthy("slot_wait_reason") {
		reason, text := record.Get("slot_wait_reason").(string)
		return reason, text
	}
	// gate.slot_place: a top-level run holds its slot while its loop lives, and waits for one
	// queued with slot_waiting
	running := 0
	alone := Every(func(_ string, other *Object) bool {
		if Equal(other.Get("run_id"), record.Get("run_id")) || other.Truthy("run_depth") {
			return true
		}
		if other.Str("state") == "running" && ProcessActive(other) {
			running++
		}
		return other.Str("state") != "queued" || !other.Truthy("slot_waiting")
	})
	limit, err := config.MaxRuns()
	wait := record.Dict("waiting_on")
	first := record.Truthy("first") || wait != nil && (wait.Has("land") || wait.Has("fix"))
	if !alone || err != nil || limit > 0 && running >= limit && !first {
		return "", false
	}
	return "waiting for a slot · 0 ahead", true
}
