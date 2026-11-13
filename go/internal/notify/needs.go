package notify

import (
	"context"
	"io"
	"time"

	"agentkit/internal/run"
)

// Needs is ak's own question about a seat, Python's shaped with an event id: recorded beside the
// standing question, once for its event, and its card evaluated with shaped's zero wait on the
// word and last input.  False where that card is Python's to evaluate, the question written then
// only where `kept`: Go reads no word but the one published since, so a question it just put to
// the seat is kept on record for the word to turn, and any other is Python's, nothing written.
func Needs(name, text, source string, kept bool, published func(string) (string, any), errOut io.Writer) (bool, error) {
	return needs(name, text, source, kept, false, looked(published), errOut)
}

// needs is Needs on the word `asked` says the seat says once the notice stands, carded as a need
// where it is a `failure`, which is no question (watch.session_state's question).
func needs(name, text, source string, kept, failure bool, asked Asked, errOut io.Writer) (bool, error) {
	if Suppressed(false, errOut) {
		return true, nil
	}
	// asking is the notice once it asks this, nil where Go does not read the one it replaces
	asking := func(current string) (previous, notice *run.Object) {
		previous = open(current)
		if previous != nil && previous.Str("source") == source {
			return previous, previous
		}
		notice, read := said(current, []Kept{{Text: text}}, previous, false)
		if !read {
			return previous, nil
		}
		notice.Set("source", source)
		return previous, notice
	}
	write := func(current string, previous, notice *run.Object) error {
		if notice == previous {
			return nil
		}
		return writeNotice(current, notice)
	}
	if kept {
		known := true
		err := Held(context.Background(), name, func(current string) error {
			previous, notice := asking(current)
			if notice == nil {
				known = false
				return nil
			}
			return write(current, previous, notice)
		})
		if err != nil || !known {
			return known, err
		}
	}
	var previous, notice *run.Object
	var question bool
	said := func(current string) (string, any) {
		if previous, notice = asking(current); notice == nil {
			return "", nil
		}
		word, since, is := asked(current, notice, time.Now())
		question = is
		return word, since
	}
	var asks func(file, notice *run.Object) bool
	if !failure {
		asks = func(*run.Object, *run.Object) bool { return question }
	}
	return questionTransition(name, said, clock, 0, errOut, asks, func(current string, file *run.Object) *run.Object {
		if notice == nil || !unanswered(current, notice) || file.Str("state") == "asking" {
			return nil
		}
		return notice
	}, func(current string) error { return write(current, previous, notice) })
}
