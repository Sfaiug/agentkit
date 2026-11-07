package harness

import "agentkit/internal/run"

// Holds is the type of each piece of background work that seat's harness says it runs now, in its
// Stop's terms (hookfact.Fact's Holds), asked of it as Python's plugin `holds` is; false where it
// cannot be asked, and its last Stop's list stands.
func Holds(name string, record *run.Object) ([]string, bool) {
	if hook := plugins[name].holds; hook != nil {
		return hook(record)
	}
	return nil, false
}
