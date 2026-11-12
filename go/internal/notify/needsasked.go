package notify

import (
	"io"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// NeedsAsked is Needs carded on the word the seat says once the question stands, as Python's shaped
// reads session_state after recording it: nothing is written where Go does not card it now.
func NeedsAsked(name, text, source string, asked Asked, errOut io.Writer) (bool, error) {
	return needs(name, text, source, false, asked, errOut)
}

// looked is the word a seat's look published as an Asked, the question's only where the look
// published it as the word's reason.
func looked(published func(string) (string, any)) Asked {
	return func(name string, notice *run.Object, _ time.Time) (string, any, bool) {
		word, since := published(name)
		file, _ := readObject(seatFile("seat", name, "json"))
		return word, since, file != nil && reasonIs(file, notice)
	}
}

// reasonIs is whether the seat's look published that question as its word's reason.
func reasonIs(file, notice *run.Object) bool {
	return config.Fold(file.Str("reason")) == config.Fold(notice.Str("text"))
}
