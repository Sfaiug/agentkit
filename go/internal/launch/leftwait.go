package launch

import "agentkit/internal/run"

// leftToPython is whether the wait a poll leaves the run in is Python's: a run outside a suite's
// home that the poll did not let in.  Python counts such a wait in history.db, which Go writes none
// of.  Beside a history.db only reading it tells whether the poll lets the run in, and that reading
// writes beside it, so a poll that has not read it yet leaves the wait too.  A run's driver hands
// such a wait over at its poll, before anything of it is written, for Python's tick to take up.
func (a *admission) leftToPython(record *run.Object) bool {
	return !record.Truthy("notify_sink") && !a.in
}
