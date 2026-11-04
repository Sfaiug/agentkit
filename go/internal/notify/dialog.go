package notify

import (
	"slices"

	"agentkit/internal/run"
)

// unansweredSince leaves newer owner messages and deferred retirements to their Python passes.
func unansweredSince(name string, since float64) bool {
	if !retirementsDrained() {
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
	notice := run.Fields("text", file.Str("reason"), "time", file.Get("word_since"))
	if declared, _ := readObject(seatFile("notify", name, "json")); declared != nil && declared.Str("kind") == "needs" && resolved(declared) {
		if _, known := declared.Get("text").(string); known {
			// The answer still ends the old card, whose transition belongs to Python.
			notice.Set("earlier_answer_at", run.Float(max(number(declared, "answered_at"), number(declared, "earlier_answer_at"))))
		}
	}
	return notice
}
