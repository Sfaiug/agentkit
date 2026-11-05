package notify

import (
	"io"

	"agentkit/internal/run"
)

// TurnedNeed cards a published need at a quiet prompt with no question standing. Its clock is
// the word's, and its text the reason already decided by the seat's ladder.
func TurnedNeed(name string, said func(string) (string, any), errOut io.Writer) (bool, error) {
	return turnedNeed(name, said, clock, errOut)
}

func turnedNeed(name string, said func(string) (string, any), clock func() float64, errOut io.Writer) (bool, error) {
	return questionTransition(name, said, clock, cardWait, errOut, false, quietNeed)
}

// UnansweredNeed leaves a standing non-question to its card row when no owner message answers it.
func UnansweredNeed(name string) bool {
	file, _ := readObject(seatFile("seat", name, "json"))
	notice := quietNeed(name, file)
	return notice != nil && unansweredSince(name, number(notice, "time"))
}

func quietNeed(name string, file *run.Object) *run.Object {
	if file == nil || file.Str("word") != "needs you" || Last(name) != nil || file.Truthy("unasked") ||
		file.Str("state") != "at_prompt" && file.Str("state") != "draft" {
		return nil
	}
	if _, dated := finite(file.Get("word_since")); !dated {
		return nil
	}
	return run.Fields("text", file.Str("reason"), "time", file.Get("word_since"))
}
