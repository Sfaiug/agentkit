package cli

import (
	"strings"
	"unicode"

	"agentkit/internal/run"
)

// cardReplies is the owner's answer on the harness's own question tool, as hooks/seat-state.sh
// reads it: each answer holding any words, as the question it answers, by its words or by an id
// its call gives the words of, then the choices the card showed with it.  Nil for none, for a
// sub-agent's tool, and for an event that answers nothing of theirs.
func cardReplies(event *run.Object) [][]string {
	if first(event, subAgent...) != nil || ownersWords(event) == nil {
		return nil
	}
	answers := within(event, "tool_input").Get("answers")
	if answers == nil || answers == false {
		answers = within(event, "tool_response").Get("answers")
	}
	given, _ := answers.(*run.Object)
	if given == nil {
		return nil
	}
	var replies [][]string
	for _, id := range given.Keys() {
		if !worded(given.Get(id)) {
			continue
		}
		asked := run.NewObject()
	found:
		for _, call := range []string{"tool_input", "tool_response"} {
			for _, each := range within(event, call).List("questions") {
				if question, _ := each.(*run.Object); question != nil && (question.Get("id") == id || question.Get("question") == id) {
					asked = question
					break found
				}
			}
		}
		reply := []string{id}
		if text, ok := asked.Get("question").(string); ok {
			reply[0] = text
		}
		for _, option := range asked.List("options") {
			if choice, ok := option.(*run.Object); ok {
				option = choice.Get("label")
			}
			if label, ok := option.(string); ok {
				reply = append(reply, label)
			}
		}
		replies = append(replies, reply)
	}
	return replies
}

// within is the event's object under key, an empty one for anything else.
func within(event *run.Object, key string) *run.Object {
	if object := event.Dict(key); object != nil {
		return object
	}
	return run.NewObject()
}

// worded is whether the value holds a string with anything but space in it, at any depth.
func worded(value any) bool {
	switch value := value.(type) {
	case string:
		return strings.ContainsFunc(value, func(r rune) bool { return !unicode.IsSpace(r) })
	case []any:
		for _, each := range value {
			if worded(each) {
				return true
			}
		}
	case *run.Object:
		for _, key := range value.Keys() {
			if worded(value.Get(key)) {
				return true
			}
		}
	}
	return false
}
