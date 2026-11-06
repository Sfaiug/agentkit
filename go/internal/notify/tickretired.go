package notify

import (
	"context"

	"agentkit/internal/run"
)

// RetiredQuestion leaves a sent card's retirement to the card row once its notice is over.
func RetiredQuestion(name string) bool {
	card, err := readObject(seatFile("card", name, "json"))
	return err == nil && card != nil && card.Truthy("sent") && retiredQuestion(name, card)
}

// retiredQuestion is a question's card, sent or not, whose notice is over.
func retiredQuestion(name string, card *run.Object) bool {
	if card == nil || card.Str("word") != "needs you" || Last(name) != nil {
		return false
	}
	began := card.Get("began")
	if !card.Has("began") {
		began = card.Get("since")
	}
	at, dated := finite(began)
	return dated && at >= installedAt() && retirementsDrained()
}

// TurnedRetiredQuestion closes a question's card once its notice is gone or answered and its
// word changed. A standing question keeps its episode through independent work.
func TurnedRetiredQuestion(name string, said func(string) (string, any)) (bool, error) {
	carried := false
	err := Held(context.Background(), name, func(current string) error {
		card, err := readObject(seatFile("card", current, "json"))
		if err != nil || !retiredQuestion(current, card) {
			return err
		}
		word, since := said(current)
		if word != "idle" && word != "working" {
			return nil
		}
		if err := retire(card); err != nil {
			return err
		}
		if at, dated := finite(since); !dated || at <= number(card, "since") {
			since = run.Float(clock())
		}
		carried = true
		return writeCard(current, episode(card, word, since, since))
	})
	return carried, err
}
