package notify

import (
	"io"

	"agentkit/internal/run"
)

// Page pages the owner about no seat with line, pinging them where mention, once per key however
// often it is asked, as Python's notify.page asks for a page owed still: the outbox keeps the
// event, so no later tick queues it again, and one the webhook did not take is tried again on a
// card's schedule when asked again.  Waiting is whether it is not out yet and may still be.
func Page(key, line string, mention bool, errOut io.Writer) (waiting bool, err error) {
	page, err := cardPayload(line, mention)
	if err != nil {
		return false, err
	}
	held, err := holdOutbox()
	if err != nil {
		return false, err
	}
	defer held.Close()
	event, err := readEvent(pageKey(key))
	if err != nil {
		return false, err
	}
	settled := func() bool { return event.Str("status") == "delivered" || event.Str("status") == "disabled" }
	if event == nil {
		event = run.Fields("id", pageKey(key), "session", nil, "kind", "needs", "text", line, "payload", page,
			"message", line, "created_at", run.Float(clock()), "sink", sink() != "", "status", "pending",
			"attempts", 0, "next_attempt", 0)
		if err := writeEvent(event); err != nil {
			return false, err
		}
	} else if !settled() {
		run.SetAll(event, "text", line, "payload", page, "message", line) // what is true now, until out
	}
	if _, err := attempt(event, errOut); err != nil {
		return false, err
	}
	return !settled(), nil
}

// Paged is whether the page asked for under key is out.
func Paged(key string) (bool, error) {
	event, err := readEvent(pageKey(key))
	return event != nil && event.Str("status") == "delivered", err
}

// pageKey is the outbox id of the page asked for under key, a test's apart from the owner's.
func pageKey(key string) string {
	return digest(run.Line([]any{"page", key, sink() != ""}))
}
