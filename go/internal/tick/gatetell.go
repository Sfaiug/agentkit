package tick

import (
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// tellGate is the delivery of a line agentkit's own gates owe (update.Deliver), after_merge_deliver
// with no run: no delivery lock, no NOT LIVE line and no own seat, so the seat its mark names
// while that one is up, else the newest seat up whose runs merged into the repository origin names.
func (t *ticking) tellGate(origin, line string, typed *run.Object, receipt func(*run.Object) error) (string, error) {
	return t.tellSeat("", loop.RemoteKey(origin), line, typed, receipt)
}
