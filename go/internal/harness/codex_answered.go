package harness

import (
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A Plan-mode turn asks with codexPlanTool, which waits in a dialog of the seat's own, an async
// card with codexCardTool (codex.py PLAN_TOOL and QUESTION_TOOL).  Codex 0.163 writes the owner's
// answers on an async card as a message of theirs between codexReply's tags; Codex 0.167 keeps a
// Plan-mode card's as its call's output, a note the owner added to a pick after codexNote.
const (
	codexPlanTool, codexCardTool = "request_user_input", "request_user_input_async"
	codexReply, codexReplyEnd    = "<send_user_message_question_reply>", "</send_user_message_question_reply>"
	codexNote                    = "user_note: "
)

// codexReplies is whether that message of the owner's is their reply on an async card, which
// repeats the seat's question as if they had said it: the done check counts it only as the answers
// it gave (codex.py `user_messages`' `replies`).
func codexReplies(text string) bool { return strings.HasPrefix(text, codexReply) }

// codexTyped is each message of the owner's in the thread the record's receipt proves its, dated
// (codex.py `user_messages`), and the error where that receipt or its rollout is there and cannot
// be read.
func codexTyped(record map[string]any, _ string) ([]Prompt, error) {
	_, typed, _, err := codexWords(record)
	return typed, err
}

// codexAnswered is that thread as its rollout shows it (codex.py `said`) and each answer the owner
// gave on its cards (`answers`), read as strictly as codexTyped.
func codexAnswered(record map[string]any) ([]Turn, []Card, error) {
	said, _, cards, err := codexWords(record)
	return said, cards, err
}

// codexWords reads the rollout once as codex.py's `lines` does: each completed UserMessage is the
// user side's turn, and the owner's message where it is dated; each completed AgentMessage the
// model's; and each card call asked so far answers by a later reply or output.  None where the
// record proves no thread or its rollout is gone; what was read beside the error that stopped it.
func codexWords(record map[string]any) (said []Turn, typed []Prompt, cards []Card, err error) {
	_, rollout, err := codexRollout(record)
	if rollout == "" {
		return nil, nil, nil, err
	}
	calls := map[[2]string][]*run.Object{} // each card's questions, by its tool and call
	err = Entries(rollout, func(entry *run.Object) {
		if tool, call, asked := codexCard(entry); asked != nil {
			calls[[2]string{tool, call}] = asked
		}
		if text := codexCompleted(entry, "UserMessage"); text != "" {
			said = append(said, Turn{"user", text})
			if at := Moment(entry.Get("timestamp")); at != 0 {
				typed = append(typed, Prompt{at, text})
				if codexReplies(text) {
					cards = append(cards, codexReplied(text, at, calls)...)
				}
			}
		} else if text := codexCompleted(entry, "AgentMessage"); text != "" {
			said = append(said, Turn{"model", text})
		}
		cards = append(cards, codexPicked(entry, calls)...)
	})
	return said, typed, cards, err
}

// codexCompleted is the text of the completed item of that kind a rollout line holds, "" for none
// (codex.py `completed`): a UserMessage's parts are `text`, an AgentMessage's `Text`.
func codexCompleted(entry *run.Object, kind string) string {
	payload := entry.Dict("payload")
	if entry.Str("type") != "event_msg" || payload == nil || payload.Str("type") != "item_completed" ||
		payload.Dict("item") == nil || payload.Dict("item").Str("type") != kind {
		return ""
	}
	var said []string
	for _, part := range payload.Dict("item").List("content") {
		if part, _ := part.(*run.Object); part != nil && (part.Str("type") == "text" || part.Str("type") == "Text") {
			if text, ok := part.Get("text").(string); ok {
				said = append(said, text)
			}
		}
	}
	return strings.Join(said, "\n")
}

// codexCard is the tool, call and questions of a card a rollout line asks, each question an
// object; nil questions for anything else.
func codexCard(entry *run.Object) (tool, call string, asked []*run.Object) {
	payload := entry.Dict("payload")
	if payload == nil || entry.Str("type") != "response_item" || payload.Str("type") != "function_call" {
		return "", "", nil
	}
	names := strings.Split(payload.Str("name"), ".")
	tool = names[len(names)-1]
	call, named := payload.Get("call_id").(string)
	arguments, _ := run.DecodeShown([]byte(payload.Str("arguments")))
	questions, _ := arguments.(*run.Object)
	if tool != codexPlanTool && tool != codexCardTool || !named || questions == nil || questions.List("questions") == nil {
		return "", "", nil
	}
	asked = []*run.Object{}
	for _, each := range questions.List("questions") {
		question, _ := each.(*run.Object)
		if question == nil {
			return "", "", nil
		}
		asked = append(asked, question)
	}
	return tool, call, asked
}

// codexReplied is each answer an async card's reply, written at, gives: a reply names its card's
// call and the question's index, and the answer is text, not blank, to a question whose options
// are a list.  A reply naming no card asked answers nothing.
func codexReplied(text string, at float64, calls map[[2]string][]*run.Object) (cards []Card) {
	cut := strings.LastIndex(text, codexReplyEnd)
	if cut < 0 || strings.TrimFunc(text[cut+len(codexReplyEnd):], config.Space) != "" {
		return nil
	}
	_, body, _ := strings.Cut(text[:cut], ">")
	replies, _ := run.DecodeShown([]byte(body))
	listed, _ := replies.([]any)
	for _, each := range listed {
		reply, _ := each.(*run.Object)
		if reply == nil {
			continue
		}
		id, _ := run.DecodeShown([]byte(reply.Str("questionItemId")))
		item, _ := id.([]any)
		if len(item) != 3 || item[0] != codexCardTool {
			continue
		}
		call, named := item[1].(string)
		number, _ := item[2].(run.Number)
		index, err := strconv.Atoi(string(number))
		asked := calls[[2]string{codexCardTool, call}]
		answer, _ := reply.Get("answer").(string)
		if !named || !run.Integral(number) || err != nil || index < 0 || index >= len(asked) ||
			strings.TrimFunc(answer, config.Space) == "" {
			continue
		}
		options, listed := asked[index].Get("options").([]any)
		if !listed {
			continue
		}
		choices := []Choice{}
		for _, option := range options {
			choices = append(choices, Choice{run.Text(option), ""})
		}
		cards = append(cards, Card{at, run.Text(asked[index].Get("title")), answer, choices})
	}
	return cards
}

// codexPicked is each answer a Plan-mode card's output holds, if that rollout line is one (codex.py
// `picked`): the owner answers that card in the seat's own screen, and Codex keeps no message of
// theirs, only their pick, then any note they added, under each question's id.  A question with no
// answer under its id, or of any other shape, answers nothing.
func codexPicked(entry *run.Object, calls map[[2]string][]*run.Object) (cards []Card) {
	payload, at := entry.Dict("payload"), Moment(entry.Get("timestamp"))
	if payload == nil || entry.Str("type") != "response_item" || payload.Str("type") != "function_call_output" || at == 0 {
		return nil
	}
	call, named := payload.Get("call_id").(string)
	asked, known := calls[[2]string{codexPlanTool, call}]
	output, _ := run.DecodeShown([]byte(payload.Str("output")))
	given, _ := output.(*run.Object)
	if !named || !known || given == nil || !given.Has("answers") {
		return nil
	}
	answers, _ := given.Get("answers").(*run.Object)
	for _, question := range asked {
		if card, ok := codexPick(question, answers, at); ok {
			cards = append(cards, card)
		}
	}
	return cards
}

// codexPick is the answer given at that time to that Plan-mode question, its choices each a label and a
// description beside it: the pick, which comes first, keeps every word of a label that begins
// like a note, and each note after it loses that beginning.
func codexPick(question, answers *run.Object, at float64) (Card, bool) {
	id, named := question.Get("id").(string)
	if !named || answers == nil || !answers.Has(id) || !question.Has("question") {
		return Card{}, false
	}
	given, _ := answers.Get(id).(*run.Object)
	if given == nil || !given.Has("answers") {
		return Card{}, false
	}
	words, listed := given.Get("answers").([]any)
	options, offered := question.Get("options").([]any)
	if !listed || question.Truthy("options") && !offered {
		return Card{}, false
	}
	choices, labels := []Choice{}, map[string]bool{}
	for _, each := range options {
		option, _ := each.(*run.Object)
		if option == nil || !option.Has("label") {
			return Card{}, false
		}
		switch label := option.Get("label").(type) {
		case *run.Object, []any: // no label Python can hash
			return Card{}, false
		case string:
			labels[label] = true
		}
		description := ""
		if option.Truthy("description") {
			description = run.Text(option.Get("description"))
		}
		choices = append(choices, Choice{run.Text(option.Get("label")), description})
	}
	answer := make([]string, len(words))
	for n, each := range words {
		text, isText := each.(string)
		if !isText {
			return Card{}, false
		}
		if answer[n] = text; n > 0 || !labels[text] {
			answer[n] = strings.TrimPrefix(text, codexNote)
		}
	}
	return Card{at, run.Text(question.Get("question")), strings.Join(answer, "\n"), choices}, true
}
