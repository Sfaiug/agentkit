package harness

import "agentkit/internal/run"

// Reconcile is the fields that harness writes into a seat's record before anything claims the seat
// resumable (Python's plugin.reconcile), judged on the record as its lock holds it; none where Go
// leaves that harness's reconcile to Python.
func Reconcile(name string, record *run.Object) *run.Object {
	if hook := plugins[name].reconcile; hook != nil {
		return hook(record)
	}
	return run.NewObject()
}
