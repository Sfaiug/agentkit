// Package harness holds what a harness brings beyond its adapter's manifest, as Python's
// agentkit/harness/<name>.py does: each hook answered by that harness's own where it has one,
// by the default elsewhere.
package harness

// A plugin is one harness's own answers; a hook it leaves nil takes the default.
type plugin struct {
	identity  func(text string, argv []string) (string, bool)
	snapshots bool
}

var plugins = map[string]plugin{}

// Identity is a harness's `[update] version` output as a build identity, refined where it has
// more to say; false where it reads what Go cannot read as Python does.
func Identity(name, text string, argv []string) (string, bool) {
	if hook := plugins[name].identity; hook != nil {
		return hook(text, argv)
	}
	return text, true
}

// Snapshots is whether an upgrade of that harness is put back from a local snapshot it takes
// itself; otherwise its `[update] revert` puts it back, or nothing can.
func Snapshots(name string) bool {
	return plugins[name].snapshots
}
