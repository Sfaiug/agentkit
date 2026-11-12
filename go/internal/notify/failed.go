package notify

import (
	"io"
	"time"

	"agentkit/internal/run"
)

// Failed is ak's own failure about a seat, a recovery it could not carry out (watch.revive_seats'
// shaped): recorded once for its event and kept, then carded as Needs cards a question, on the
// seat's word as `word` reads it with the notice standing.  A failure is no question: its card goes
// out with its own text, whoever is in the seat.
func Failed(name, text, source string, word func(string) (string, any), errOut io.Writer) (bool, error) {
	return needs(name, text, source, true, true, func(name string, _ *run.Object, _ time.Time) (string, any, bool) {
		said, since := word(name)
		return said, since, false
	}, errOut)
}
