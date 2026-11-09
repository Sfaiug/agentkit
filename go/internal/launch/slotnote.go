package launch

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// SlotNote is Python's gate.slot_note, the line under a queued run: a run behind the first in
// runs/.slots.queue reads its place there, any other its own reason, else its place as
// gate.slot_counts counts it.  False where Go does not read it: a queue Go reads otherwise than
// Python (queued), a reason that is no text, another run waiting for a slot whose order against
// this one is gate.slot_counts', or a full count that asks whether the run goes first as an
// install's fix (run.FirstPlaceTold).
func SlotNote(record *run.Object) (string, bool) {
	saved, read := queued()
	if !read {
		return "", false
	}
	running, ahead := saved.running, slices.Index(saved.queue, record.Str("run_id"))
	if ahead < 1 {
		if record.Truthy("slot_wait_reason") {
			reason, text := record.Get("slot_wait_reason").(string)
			return reason, text
		}
		holders, waiting, read := places(record)
		if !read || len(waiting) > 0 {
			return "", false
		}
		running, ahead = len(holders), 0
	}
	limit, err := config.MaxRuns()
	first := !order(record)[0]
	if err != nil || limit > 0 && running >= limit && !first && run.FirstPlaceTold() {
		return "", false
	}
	return slotLine(running, ahead, limit, first), true
}
