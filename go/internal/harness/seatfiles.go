package harness

import (
	"maps"
	"slices"

	"agentkit/internal/run"
)

// Reconciled is what a listing writes into a seat's record of that harness before it reads it as
// resumable (Python's plugin `reconcile`), nil for nothing: where the default would drop a
// conversation the launcher did not hand out, Go follows no such record.
func Reconciled(name string, record *run.Object) *run.Object {
	if hook := plugins[name].reconcile; hook != nil {
		return hook(record)
	}
	return nil
}

// RecordKeys are the keys a seat's record of that harness holds beyond every seat's, as its plugin
// writes them.
func RecordKeys(name string) []string { return plugins[name].keys }

// KeptInState is whether some harness keeps that state/ entry beside its seats' records.
func KeptInState(entry string) bool {
	return slices.ContainsFunc(slices.Collect(maps.Values(plugins)), func(own plugin) bool {
		return own.kept != nil && own.kept.MatchString(entry)
	})
}
