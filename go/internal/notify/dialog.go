package notify

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// unansweredSince leaves newer owner messages and deferred retirements to their Python passes.
func unansweredSince(name string, since float64) bool {
	if !config.Listable(outbox()) || len(config.Glob(outbox(), "*.clear")) != 0 {
		return false
	}
	said, err := OwnerSaid(name)
	return err == nil && !slices.ContainsFunc(said, func(at float64) bool { return at > since })
}

// UnansweredDialog says typed answers has nothing to do while this dialog still stands.
func UnansweredDialog(name string) bool {
	file, _ := readObject(seatFile("seat", name, "json"))
	return dialogQuestion(name, file) != nil
}

func dialogQuestion(name string, file *run.Object) *run.Object {
	if file == nil || file.Str("state") != "asking" || file.Str("word") != "needs you" || Last(name) != nil {
		return nil
	}
	if kept := file.Dict("unasked"); kept != nil {
		if kept.Has("ended") {
			return nil
		}
		for _, value := range kept.List("questions") {
			if question, ok := value.(*run.Object); !ok || question.Has("ended") {
				return nil // an earlier question's turn ended: its notice is still owed
			}
		}
	}
	when, dated := finite(file.Get("word_since"))
	if !dated || !unansweredSince(name, when) {
		return nil
	}
	return run.Fields("text", file.Str("reason"), "time", file.Get("word_since"))
}
