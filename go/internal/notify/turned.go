package notify

import (
	"context"
	"errors"
	"slices"

	"agentkit/internal/run"
)

// Turned is the tick's card transition of a seat (notify.transition), under the seat's lock, where
// neither its card nor its word is one a card goes out for: a card of another word gives way to a
// new episode of this one, unsent, begun when the word did.  said reads the word and since when
// under that lock, as the seat's last announce published them.  A card dated at or after that is the
// word the last transition carded, so a word other than its began at this transition.  False, with
// nothing written, where the card or the word is `needs you` or `done`, or no word was published.
func turned(name string, said func(current string) (word string, since any), done func(string, *run.Object, any) (bool, error)) (bool, error) {
	carried := false
	err := Held(context.Background(), name, func(current string) error {
		card, err := readObject(seatFile("card", current, "json"))
		if err != nil && !errors.Is(err, errNotObject) {
			return err
		}
		if card == nil {
			card = run.NewObject()
		}
		word, since := said(current)
		if word == "done" && done != nil && card.Str("word") != "needs you" {
			var err error
			carried, err = done(current, card, since)
			return err
		}
		carded := card.Get("word")
		if carried = word != "" && !slices.Contains([]any{"needs you", "done"}, carded) && word != "needs you" && word != "done"; !carried ||
			run.Equal(carded, word) {
			return nil
		}
		at, _ := finite(since)
		if _, dated := finite(since); !dated || len(card.Keys()) > 0 && carded != nil && at <= number(card, "since") {
			since = run.Float(clock())
		}
		return writeCard(current, episode(card, word, since, since))
	})
	return carried, err
}
