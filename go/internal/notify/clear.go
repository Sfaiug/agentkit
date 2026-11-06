package notify

import (
	"context"
	"time"

	"agentkit/internal/run"
)

// Clear retires the notice of a conversation the seat moved away from, as
// notify.clear does after watch.forget cleared its kept questions.
func Clear(name string) error {
	return Held(context.Background(), name, func(current string) error {
		notice := open(current)
		if notice == nil || notice.Truthy("seen") {
			return nil
		}
		return over(current, notice)
	})
}

// over ends the episode of the seat's notice as an answer does, so a question asked before the next
// tick gets a card of its own: a card Discord has not taken never goes out, a needs-you card keeps
// the answer, and the notice is seen, under the name the seat goes by now.
func over(name string, notice *run.Object) error {
	card, err := readObject(seatFile("card", name, "json"))
	if err != nil && err != errNotObject {
		return err
	}
	if card != nil {
		if err := retire(card); err != nil {
			return err
		}
		if card.Str("word") == "needs you" {
			card.Set("answered_at", run.Float(float64(time.Now().UnixNano())/1e9))
			if err := writeCard(name, card); err != nil {
				return err
			}
		}
	}
	notice = notice.Copy()
	notice.Set("session", name)
	notice.Set("seen", true)
	return writeNotice(name, notice)
}
