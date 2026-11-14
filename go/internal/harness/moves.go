package harness

import "agentkit/internal/run"

// Moves is whether a hook's event may move a seat of that harness to the conversation it names
// (Python's plugin `follow`) where Follows does not carry the move, which Go leaves to Python.
func Moves(name string, event *run.Object) bool {
	hook := plugins[name].moves
	return hook != nil && hook(event)
}
