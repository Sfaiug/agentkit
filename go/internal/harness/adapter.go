package harness

import (
	"io"

	"agentkit/internal/run"
)

// verbs holds the adapter verbs Go carries out for one harness alone, by that harness and verb
// (`opencode variants`); each one's file adds itself, as a command joins cli's commands.
var verbs = map[string]func(args []string, out, errOut io.Writer) int{}

// Verb is that harness's own adapter verb of that name, nil where it has none.
func Verb(name, verb string) func(args []string, out, errOut io.Writer) int {
	return verbs[name+" "+verb]
}

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

// HookFollows is the conversation an adapter's hook event, as HookEvent read it, says the seat's
// own client went on in, or keeps, as that harness's plugin `follow` reads it: nil for none.
func HookFollows(name string, event *run.Object) *Followed {
	if hook := plugins[name].follows; hook != nil && event != nil {
		return hook(event)
	}
	return nil
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
