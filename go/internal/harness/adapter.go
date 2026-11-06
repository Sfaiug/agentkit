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

// Serve runs the seat's words on terminal, the seat's own, as its harness runs a seat: those words
// alone, unless what it runs beside them is the harness's to start and end, which calls changed where
// it tells of a change the seat's screen may not show.  It answers the seat's exit code.
func Serve(name string, words, env []string, errOut io.Writer, terminal func(words, env []string) int, changed func()) int {
	if hook := plugins[name].serve; hook != nil {
		return hook(words, env, errOut, terminal, changed)
	}
	return terminal(words, env)
}

// HookEvent reads an adapter's payload into the shape the shared seat hook takes; nil is silent,
// with the hook's exit code where the harness answered the event itself, on out.  refused is why
// that seat may not ask a question now, "" where it may, and reconciled writes Reconcile into that
// seat's record.
func HookEvent(name string, event *run.Object, out io.Writer, refused func(seat string) (string, error),
	reconciled func(seat string)) (*run.Object, int) {
	if hook := plugins[name].hookEvent; hook != nil && event != nil {
		return hook(event, out, refused, reconciled)
	}
	return nil, 0
}
