package tick

import (
	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// waitLine is what a seat whose wait is over hears: one line, whatever its fact said over several,
// since a newline typed is a key of its own.
func waitLine(wait *run.Object) string {
	return config.Fold(run.Text(wait.Get("over"))) + "; your wait is over. Decide the next step."
}

// tellLive is watch.wait_over's line to a seat still up whose wait on a job is over: typed through
// the confirmed send only at its quiet prompt, the send's receipt kept on the wait, and the wait
// told once the seat has it; a seat mid-turn is tried again next tick.  A wait on anything else, a
// harness Go does not type into, a line too long to type whole and one ak's editor took in are
// Python's.
func (t *ticking) tellLive(name string, wait *run.Object) error {
	line, typed := waitLine(wait), wait.Dict("typed")
	if wait.Str("kind") != "job" || !seat.Typable(name) || config.TooLong(line) || typed != nil && typed.Has("pane") {
		return errLeft
	}
	var kept error
	if !seat.TypeAtPrompt(name, line, typed, func(mark *run.Object) error {
		_, kept = seat.MarkWait(name, wait, "typed", mark)
		return kept
	}, t.log.line) {
		return kept
	}
	if told, err := seat.MarkWait(name, wait, "told", run.Float(epoch(t.clock()))); err != nil || told == nil {
		return err
	}
	t.log.line(name + ": told that " + run.Text(wait.Get("over")) + "; its wait is over")
	return nil
}
