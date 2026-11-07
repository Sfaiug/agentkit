package harness

import (
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// museAnswered reads the session the seat's receipt names once for muse.py's `said` and
// `answers`: its conversation as museSaid reads it, and each question the owner answered on one
// of its question cards.  Unlike museSaid's, this read is the done check's: a receipt or log that
// may be there and cannot be read is an error, never an owner who said nothing.
func museAnswered(record map[string]any) (said []Turn, cards []Card, err error) {
	session, err := museConversationFound(record)
	if err != nil {
		return nil, nil, err
	}
	log, err := museLogFound(session)
	if err != nil {
		return nil, nil, err
	}
	answered, asked := map[string]bool{}, map[[2]string]map[string]*run.Object{}
	err = Entries(log, func(entry *run.Object) {
		if turn, shown := museTurn(entry, answered); shown {
			said = append(said, turn)
		}
		cards = append(cards, museCards(entry, asked)...)
	})
	return said, cards, err
}

// museCards is each question that line answers on a card asked before it, adding the card it
// asks itself, by its prompt and tool call as museCard names one: a settling `answered`, dated
// when Muse recorded it, picks each answer's label from its question's options.  Any other
// settling answers nothing, and neither does a line any part of which has another shape, an
// answer to a question the card did not ask among them.  An answer counts only where it is text
// and not blank, beside a question and choices all text.
func museCards(entry *run.Object, asked map[[2]string]map[string]*run.Object) []Card {
	if request := museRunEvent(entry, "user_input_prompt_requested"); request != nil {
		prompt, named := request.Get("prompt_id").(string)
		call, called := request.Get("tool_call_id").(string)
		if questions, ok := museQuestions(request); ok && named && called && request.Get("tool_name") == "request_user_input" {
			asked[[2]string{prompt, call}] = questions
		}
		return nil
	}
	done := museRunEvent(entry, "user_input_prompt_settled")
	micro, whole := entry.Int("recorded_at")
	if done == nil || done.Get("outcome") != "answered" || !whole {
		return nil
	}
	prompt, named := done.Get("prompt_id").(string)
	call, called := done.Get("tool_call_id").(string)
	questions, ok := asked[[2]string{prompt, call}]
	answers, listed := done.Get("answers").([]any)
	if !named || !called || !ok || !listed {
		return nil
	}
	var found []Card
	for _, each := range answers {
		picked, _ := each.(*run.Object)
		if picked == nil {
			return nil
		}
		id, isText := picked.Get("id").(string)
		question, ok := questions[id]
		if !isText || !ok || !question.Has("question") || !picked.Has("selected_label") {
			return nil
		}
		asking, text := question.Get("question").(string)
		answer, picks := picked.Get("selected_label").(string)
		text = text && picks && strings.TrimFunc(answer, config.Space) != ""
		var choices []Choice
		for _, value := range question.List("options") {
			option, _ := value.(*run.Object)
			if option == nil || !option.Has("label") {
				return nil
			}
			label, labelled := option.Get("label").(string)
			description, described := "", true
			if option.Has("description") {
				description, described = option.Get("description").(string)
			}
			text = text && labelled && described
			choices = append(choices, Choice{label, description})
		}
		if text {
			found = append(found, Card{float64(micro) / 1e6, asking, answer, choices})
		}
	}
	return found
}

// museQuestions is each question a card's request asks, by its id: those whose id is text and
// whose options are a list.  False where its questions are no list of objects each with an id,
// or one with a text id has no options.
func museQuestions(request *run.Object) (map[string]*run.Object, bool) {
	listed, ok := request.Get("questions").([]any)
	if !ok {
		return nil, false
	}
	questions := map[string]*run.Object{}
	for _, each := range listed {
		question, _ := each.(*run.Object)
		if question == nil || !question.Has("id") {
			return nil, false
		}
		id, named := question.Get("id").(string)
		if named && !question.Has("options") {
			return nil, false
		}
		if _, options := question.Get("options").([]any); named && options {
			questions[id] = question
		}
	}
	return questions, true
}
