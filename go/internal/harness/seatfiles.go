package harness

import (
	"maps"
	"slices"

	"agentkit/internal/run"
)

// A Reader keeps a harness's evidence at the start of one listing, apart from Python's record.
type Reader struct {
	Name string
	own  plugin
}

func For(name string) Reader { return Reader{name, plugins[name]} }

// Reconciled reads the evidence once, where Python's orch.records calls plugin.reconcile.
// False leaves a record owed reconciliation to Python, before the listing writes anything.
func (reader Reader) Reconciled(name string, record *run.Object) (Reader, bool) {
	if hook := reader.own.record; hook != nil {
		own, ready := hook(name, record)
		if !ready {
			return Reader{reader.Name, own}, false
		}
		reader.own = own
	}
	return reader.hearing(name), true
}

// RecordReadOnly keeps a harness's own reconciliation out of what a listing writes, for Python or
// the tick's Reconcile, including when the record changes between Go reading it and publishing its
// seat's word.
func RecordReadOnly(name string) bool { return plugins[name].record != nil }

// RecordKeys are the keys a seat's record of that harness holds beyond every seat's, as its plugin
// writes them.
func RecordKeys(name string) []string { return plugins[name].keys }

// LaunchKeys are what a launch writes about the conversation it owns, its harness's receipt, and
// the title that launch takes (harness.LAUNCH_KEYS).
var LaunchKeys = []string{"conversation", "resumable", "id_source", "before", "codex_launch", "codex_history",
	"opencode_launch", "muse_launch", "antigravity_launch", "antigravity_open", "session_title", "title_sync"}

// KeptInState is whether some harness keeps that state/ entry beside its seats' records.
func KeptInState(entry string) bool {
	return slices.ContainsFunc(slices.Collect(maps.Values(plugins)), func(own plugin) bool {
		return own.kept != nil && own.kept.MatchString(entry) || own.report != nil && reportFile.MatchString(entry)
	})
}
