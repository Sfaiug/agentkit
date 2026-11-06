package handback

import (
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// What came of a line for a seat (job.job_hand_back's answer).
const (
	Sent = "sent" // typed in at its quiet prompt
	Busy = "busy" // there mid-turn, or asleep and not back yet: the line waits for its next quiet prompt
	Gone = "gone" // nobody there to take it
)

// Tell is how every line ak owes a seat goes in: a seat asleep is woken first, back on its
// conversation (seat.Wake), and the line typed at its quiet prompt.  A line its mark `typed` says
// is in the composer already only gets its Enter; `receipt` keeps the mark of one typed now.
// "" where Go does not wake that seat, before anything is done.
func Tell(name, line string, typed *run.Object, receipt func(*run.Object) error, say func(string)) string {
	awake, carried := seat.Wake(name, say)
	switch {
	case !carried:
		return ""
	case !awake:
		return Busy
	case !seat.Watching(name):
		return Gone
	case seat.TypeAtPrompt(name, line, typed, receipt, say):
		return Sent
	}
	return Busy
}
