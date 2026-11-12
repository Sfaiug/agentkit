package seat

import (
	"time"

	"agentkit/internal/run"
)

// revivalWord is a seat's word once its failed revival is kept on record, as Python's shaped reads
// session_state after recording it: the card's word, the ladder as it reads now.  It is never the
// question: a revival comes only to a seat that is not live, and only a seat somebody is in has a
// question for its word.
func revivalWord(name string, _ *run.Object, _ time.Time) (string, any, bool) {
	word, since := CardWord(name)
	return word, since, false
}
