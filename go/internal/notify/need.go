package notify

import (
	"io"

	"agentkit/internal/run"
)

// TurnedNeed cards a need at a quiet prompt with no question standing, as the seat's ladder words
// it now (needs_transition's answer): its clock is the word's, and its text the reason the climb
// gives, which a row since the look may have changed, a line typed in that ended the wait it read.
func TurnedNeed(name string, answer func(string) (word, reason string, since any), errOut io.Writer) (bool, error) {
	return turnedNeed(name, answer, clock, errOut)
}

func turnedNeed(name string, answer func(string) (string, string, any), clock func() float64, errOut io.Writer) (bool, error) {
	var reason string
	var since any
	said := func(current string) (string, any) {
		var word string
		word, reason, since = answer(current)
		return word, since
	}
	return questionTransition(name, said, clock, cardWait, errOut, false, func(current string, file *run.Object) *run.Object {
		return quietNeed(current, file, reason, since, clock)
	}, func(string) error { return nil })
}

func quietNeed(name string, file *run.Object, reason string, since any, clock func() float64) *run.Object {
	if Last(name) != nil || file.Truthy("unasked") || file.Str("state") != "at_prompt" && file.Str("state") != "draft" {
		return nil
	}
	if since == nil {
		since = undated(name, clock)
	}
	if _, dated := finite(since); !dated {
		return nil
	}
	return run.Fields("text", reason, "time", since)
}
