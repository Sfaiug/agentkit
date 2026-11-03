package notify

import (
	"context"
	"errors"

	"agentkit/internal/run"
)

// Turned is the tick's card transition of a seat whose word is neither `needs you` nor `done`
// (notify.transition), under the seat's lock: a card of another word gives way to a new episode of
// this one, unsent, begun when the word did.  said reads the word and since when under that lock,
// as the seat's last announce published them.  A card dated at or after that is the word the last
// transition carded, so a word other than its began at this transition.
func Turned(name string, said func(current string) (word string, since any)) error {
	return Held(context.Background(), name, func(current string) error {
		card, err := readObject(seatFile("card", current, "json"))
		if err != nil && !errors.Is(err, errNotObject) {
			return err
		}
		if card == nil {
			card = run.NewObject()
		}
		word, since := said(current)
		if run.Equal(card.Get("word"), word) {
			return nil
		}
		at, _ := finite(since)
		if _, dated := finite(since); !dated || len(card.Keys()) > 0 && card.Get("word") != nil && at <= number(card, "since") {
			since = run.Float(clock())
		}
		return writeCard(current, episode(card, word, since, since))
	})
}

// CardWord is the word the seat's card holds, "" for none.
func CardWord(name string) string {
	card, _ := readObject(seatFile("card", name, "json"))
	if card == nil {
		return ""
	}
	return card.Str("word")
}
