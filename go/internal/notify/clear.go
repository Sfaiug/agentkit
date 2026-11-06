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
		card, err := readObject(seatFile("card", current, "json"))
		if err != nil && err != errNotObject {
			return err
		}
		if card != nil {
			if err := retire(card); err != nil {
				return err
			}
			if card.Str("word") == "needs you" {
				card.Set("answered_at", run.Float(float64(time.Now().UnixNano())/1e9))
				if err := writeCard(current, card); err != nil {
					return err
				}
			}
		}
		notice = notice.Copy()
		notice.Set("seen", true)
		return writeNotice(current, notice)
	})
}
