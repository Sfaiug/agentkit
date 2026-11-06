package harness

import (
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// claudeNotesOnly is what a card's result records as the pick of a question the owner only wrote
// notes on (2.1.318).
const claudeNotesOnly = "(notes only)"

// claudeAnswered reads the conversation the record names once for claude.py's `said` and
// `answers`: each message of the user side or the model (claudeHandedMessage), and each question
// the owner answered on an AskUserQuestion card.
func claudeAnswered(record map[string]any) (said []Turn, cards []Card, err error) {
	asked := map[string]bool{} // the cards asked so far, by their call's id
	err = entries(claudeConversation(record), func(entry *run.Object) {
		if who, text := claudeHandedMessage(entry); text != "" {
			said = append(said, Turn{who, text})
		}
		cards = append(cards, claudeCards(entry, asked)...)
	})
	return said, cards, err
}

// claudeCards is each question that line answers on a card asked before it, adding the cards it
// asks itself, from the result Claude Code records beside the questions and options the seat
// wrote: the options picked, comma-separated, or the words typed, then the notes added, then any
// free text written in place of a pick, as recorded when the owner sent the card or went idle on
// it.  A line no one said here (claudeUnsaid), a subagent's card among them, holds no answer of the
// owner's, and neither does a line any part of which has another shape.
func claudeCards(entry *run.Object, asked map[string]bool) []Card {
	for _, key := range claudeUnsaid {
		if entry.Truthy(key) {
			return nil
		}
	}
	var parts []*run.Object
	if message := entry.Dict("message"); message != nil {
		for _, value := range message.List("content") {
			if part, ok := value.(*run.Object); ok {
				parts = append(parts, part)
			}
		}
	}
	for _, part := range parts {
		if part.Str("type") == "tool_use" && part.Str("name") == "AskUserQuestion" {
			if !part.Has("id") {
				return nil
			}
			if id, ok := part.Get("id").(string); ok {
				asked[id] = true
			}
		}
	}
	answers := false
	for _, part := range parts {
		id, ok := part.Get("tool_use_id").(string)
		answers = answers || part.Str("type") == "tool_result" && ok && asked[id]
	}
	result, at := entry.Dict("toolUseResult"), Moment(entry.Get("timestamp"))
	if !answers || at == 0 || result == nil {
		return nil
	}
	picks, notes := result.Dict("answers"), result.Dict("annotations")
	if picks == nil && result.Has("answers") || notes == nil && result.Has("annotations") {
		return nil
	}
	var found []Card
	for _, value := range result.List("questions") {
		question, _ := value.(*run.Object)
		if question == nil || !question.Has("question") {
			return nil
		}
		var pick, note any
		switch asking := question.Get("question").(type) {
		case []any, *run.Object: // a key no answer is filed under
			return nil
		case string:
			if picks != nil {
				pick = picks.Get(asking)
			}
			if notes != nil && notes.Has(asking) {
				noted, _ := notes.Get(asking).(*run.Object)
				if noted == nil {
					return nil
				}
				note = noted.Get("notes")
			}
		}
		if pick == claudeNotesOnly {
			pick = nil
		}
		var words []string
		for _, said := range []any{pick, note, result.Get("response")} {
			if text, ok := said.(string); ok && strings.TrimFunc(text, config.Space) != "" {
				words = append(words, text)
			}
		}
		if len(words) == 0 {
			continue
		}
		card := Card{At: at, Question: run.Text(question.Get("question")), Answer: strings.Join(words, "\n")}
		if question.Truthy("options") {
			options, _ := question.Get("options").([]any)
			if options == nil {
				return nil
			}
			for _, each := range options {
				option, _ := each.(*run.Object)
				if option == nil || !option.Has("label") {
					return nil
				}
				description := ""
				if option.Has("description") {
					description = run.Text(option.Get("description"))
				}
				card.Choices = append(card.Choices, Choice{run.Text(option.Get("label")), description})
			}
		}
		found = append(found, card)
	}
	return found
}
