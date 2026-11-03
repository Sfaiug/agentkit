package harness

import (
	"maps"
	"slices"

	"agentkit/internal/run"
)

// RecordReady is whether Go can read this record without Python first reconciling it.
func RecordReady(name string, record *run.Object) bool {
	if hook := plugins[name].record; hook != nil {
		return hook(record)
	}
	return true
}

// RecordReadOnly keeps a harness's own reconciliation entirely in Python, including when the
// record changes between Go reading it and publishing its seat's word.
func RecordReadOnly(name string) bool { return plugins[name].record != nil }

// RecordKeys are the keys a seat's record of that harness holds beyond every seat's, as its plugin
// writes them.
func RecordKeys(name string) []string { return plugins[name].keys }

// KeptInState is whether some harness keeps that state/ entry beside its seats' records.
func KeptInState(entry string) bool {
	return slices.ContainsFunc(slices.Collect(maps.Values(plugins)), func(own plugin) bool {
		return own.kept != nil && own.kept.MatchString(entry)
	})
}
