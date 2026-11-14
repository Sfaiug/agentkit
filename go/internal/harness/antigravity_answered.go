package harness

import (
	"bytes"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
)

// agyCard is the `steps.step_type` of a question card `ask_question` put up, which keeps its
// answer in its own step (antigravity.py `CARD`).
const agyCard = 132

// antigravityRead reads the conversation the seat owns, or the one a record of a conversation the
// seat left names (notify.Conversations), once for antigravity.py's `said` and `answers`.  It is
// the done check's read: a claim or store that is there and cannot be read is an error, never an
// owner who said nothing.
func antigravityRead(record map[string]any) ([]Turn, []Card, error) {
	conversation, err := antigravityFound(record)
	if err != nil {
		return nil, nil, err
	}
	if conversation == "" {
		conversation, _ = record["conversation"].(string)
	}
	return antigravityWords(conversation)
}

// antigravityWords is that conversation as agy shows it, oldest first, each user input and answer
// with words in it (antigravity.py `said`), and each question its owner answered on a card
// (`answers`); the error where its store is there and cannot be read (antigravitySteps).
func antigravityWords(conversation string) (said []Turn, cards []Card, err error) {
	steps, err := antigravitySteps(conversation)
	for _, step := range steps {
		if text := step.words(); text != "" {
			said = append(said, Turn{agyWords[step.kind].who, text})
		}
		cards = append(cards, step.cards()...)
	}
	return said, cards, err
}

// cards is each question the owner answered on the card that step is, dated when they answered
// it: its metadata's 8, a Timestamp.  agy 1.5.2 keeps the card as answered in its payload's 147 ->
// 2 -> 22, each question a 1 there holding its words (1), each choice (2: its id 1, its label 2),
// the id of the one picked (4) and the words written in (5).  A question with neither, as Esc
// leaves one, answers nothing; one counts only where its words and every label are there and its
// answer is not blank.
func (step agyStep) cards() (found []Card) {
	var read agyReading
	at, dated := read.timestamp(read.field(step.metadata, 8))
	if step.kind != agyCard || !dated {
		return nil
	}
	for asked := range read.fields(read.field(read.field(read.field(step.payload, 147), 2), 22), 1) {
		question, picked := read.field(asked, 1), read.field(asked, 4)
		var choices []Choice
		var given []string
		labelled := true
		for choice := range read.fields(asked, 2) {
			named, label := read.field(choice, 1), read.field(choice, 2)
			labelled = labelled && label != nil
			choices = append(choices, Choice{gitcall.Decoded(string(label)), ""})
			if picked != nil && named != nil && bytes.Equal(named, picked) && len(label) > 0 {
				given = append(given, gitcall.Decoded(string(label)))
			}
		}
		if written := read.field(asked, 5); len(written) > 0 {
			given = append(given, gitcall.Decoded(string(written)))
		}
		answer := strings.Join(given, "\n")
		if question != nil && labelled && strings.TrimFunc(answer, config.Space) != "" {
			found = append(found, Card{at, gitcall.Decoded(string(question)), answer, choices})
		}
	}
	return found
}
