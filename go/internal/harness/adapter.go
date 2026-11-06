package harness

import (
	"io"

	"agentkit/internal/run"
)

// Interactive is a harness's own seat launch where its command needs more than its manifest.
func Interactive(name string) func(root string, args []string, out, errOut io.Writer) int {
	return plugins[name].interactive
}

// SeatWords finishes a launch inside its pane, where that pane's identity is known.
func SeatWords(name string, words, env []string) []string {
	if hook := plugins[name].seatWords; hook != nil {
		return hook(words, env)
	}
	return words
}

// HookEvent reads an adapter's payload into the shape the shared seat hook takes; nil is silent.
func HookEvent(name string, event *run.Object) *run.Object {
	if hook := plugins[name].hookEvent; hook != nil && event != nil {
		return hook(event)
	}
	return nil
}
