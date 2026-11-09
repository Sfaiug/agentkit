package launch

import "agentkit/internal/run"

// gateHere is whether the gate leaves the resume of that run to Go: none decides this process's
// runs, or the run still waits in line for its slot, where its resume puts it back under a new
// driver that polls as a launch's does (waitSlot), in the place its queued_at gives it, where
// pollsHere finds that poll Go's.
func gateHere(record *run.Object) bool {
	depth, _ := runDepth()
	return !gated(depth) || record.Str("state") == "queued" && record.Truthy("slot_waiting")
}

// pollsHere is whether Go decides the resumed run's next poll for its slot as Python would, and
// carries the wait that poll leaves (leftToPython), asked under the slots lock before the resume
// reads anything that writes, as its launch's preflight finding origin/HEAD does.  A line that
// moves after is the driver's to leave to Python at that poll, as at any later one (waitSlot).
func pollsHere(record *run.Object) bool {
	if depth, _ := runDepth(); !gated(depth) {
		return true
	}
	slots, err := holdSlots()
	if err != nil {
		return false
	}
	defer slots.Close()
	decided, err := decide(record)
	return err == nil && !decided.leftToPython(record)
}
