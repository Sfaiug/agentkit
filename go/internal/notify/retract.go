package notify

import (
	"context"

	"agentkit/internal/run"
)

// Retract is notify.clear(notice=text), watch.forget's retraction of the watcher's own alert: the
// seat's notice, answered or not, retired as an answer ends it (over) where it still says text and
// is not seen yet.
func Retract(name, text string) error {
	return Held(context.Background(), name, func(current string) error {
		notice, _ := run.ReadJSON(seatFile("notify", current, "json"))
		if notice == nil || notice.Get("kind") != "needs" || notice.Truthy("seen") || notice.Get("text") != text {
			return nil
		}
		return over(current, notice)
	})
}
