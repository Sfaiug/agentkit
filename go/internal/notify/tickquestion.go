package notify

import (
	"io"

	"agentkit/internal/run"
)

// UnansweredQuestion leaves a question with a newer owner message to Python's answer pass.
func UnansweredQuestion(name string) bool { return unanswered(name, Last(name)) }

func unanswered(name string, notice *run.Object) bool {
	if !OwnerQuestion(notice) {
		return false
	}
	if _, dated := finite(notice.Get("time")); !dated {
		return false
	}
	return unansweredSince(name, spokenAt(notice))
}

// TurnedQuestion cards a standing question; the word is read again under its typing lock.
func TurnedQuestion(name string, said func(string) (string, any), errOut io.Writer) (bool, error) {
	return turnedQuestion(name, said, clock, cardWait, errOut)
}

func turnedQuestion(name string, said func(string) (string, any), clock func() float64, wait float64, errOut io.Writer) (bool, error) {
	return questionTransition(name, said, clock, wait, errOut, looked, func(current string, file *run.Object) *run.Object {
		notice := open(current)
		if notice == nil {
			return dialogQuestion(current, file)
		}
		if !UnansweredQuestion(current) || file.Str("state") == "asking" {
			return nil
		}
		return notice
	}, func(string) error { return nil })
}
