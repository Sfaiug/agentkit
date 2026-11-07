package launch

import "agentkit/internal/run"

// gateHere is whether the gate leaves the resume of that run to Go: none decides this process's
// runs, or the run still waits in line for its slot, where its resume puts it back under a new
// driver that polls as a launch's does (waitSlot), in the place its queued_at gives it, once
// firstPoll finds that poll Go's.
func gateHere(record *run.Object) bool {
	depth, _ := runDepth()
	return !gated(depth) || record.Str("state") == "queued" && record.Truthy("slot_waiting")
}

// firstPoll is ErrPython where Go would decide the resumed run's next poll for its slot otherwise
// than Python, asked under the slots lock before the resume writes anything, as a launch asks its
// first (admit).
func firstPoll(record *run.Object) error {
	if depth, _ := runDepth(); !gated(depth) {
		return nil
	}
	_, err := decide(record)
	return err
}
