package seat

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// seatReader is the reader of what that record's harness keeps of the seat, reconciled with the
// record as Python's orch.records reconciles it (plugin.reconcile): every look reads the seat's
// answer through it, the live look and the last look at a seat whose panes have exited alike, as
// a harness keeps some of it, OpenCode's and Antigravity's last answer, only in a reconciled one.
// False hands the record to Python before anything is written.
func seatReader(name string, record *run.Object, models map[string]config.Model) (harness.Reader, bool) {
	return harness.For(models[record.Str("orchestrator")].Harness).Reconciled(name, record)
}
