package handback

import (
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// What came of a line for a seat (job.job_hand_back's answer).
const (
	Sent = "sent" // typed in at its quiet prompt
	Busy = "busy" // there mid-turn, or slept and not reopened yet: the line waits for its next quiet prompt
	Gone = "gone" // nobody there to take it
)

// Tell is how every line ak owes a seat goes in: typed at its quiet prompt, owed a seat an older ak
// put to sleep until the tick reopens it (seat.Asleep).  A line its mark `typed` says is in the
// composer already only gets its Enter; `receipt` keeps the mark of one typed now.  "" where the
// mark names the pane Python's editor put the line in past a draft, before anything is done.
func Tell(name, line string, typed *run.Object, receipt func(*run.Object) error, say func(string)) string {
	switch {
	case typed != nil && typed.Has("pane"):
		return ""
	case seat.Asleep(name):
		return Busy
	case !seat.Watching(name):
		return Gone
	case seat.TypeAtPrompt(name, line, typed, receipt, say):
		return Sent
	}
	return Busy
}
