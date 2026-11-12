package notify

import (
	"context"
	"io"

	"agentkit/internal/run"
)

// Alert is a watcher's failure, kept in the seat and sent through the ordinary card outbox.
func Alert(name, text, source string, errOut io.Writer) error {
	return Held(context.Background(), name, func(current string) error {
		previous, err := readObject(seatFile("notify", current, "json"))
		if err != nil {
			return err
		}
		if previous != nil && previous.Str("source") == source {
			return nil
		}
		card, err := readObject(seatFile("card", current, "json"))
		if err != nil {
			return err
		}
		if card == nil {
			card = run.NewObject()
		}
		now := run.Float(clock())
		notice := run.Fields("session", current, "kind", "needs", "text", text, "source", source, "watcher", true, "time", now)
		if err := writeNotice(current, notice); err != nil {
			return err
		}
		_, err = page(current, episode(card, "needs you", now, now), notice, false, errOut)
		return err
	})
}

// A watcher's alert already in this episode's outbox has no further card transition.
// A newer question, or an owner's own question, still needs its ordinary transition.
func sentAlert(name, word string, card *run.Object) bool {
	if word != "needs you" || card.Str("word") != word || !card.Truthy("sent") {
		return false
	}
	notice := Last(name)
	if notice == nil || !notice.Truthy("watcher") {
		return false
	}
	event, err := readEvent(cardKey(card.Get("episode")))
	return err == nil && event != nil && event.Str("text") == notice.Str("text")
}
