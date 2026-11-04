package notify

import (
	"context"
	"io"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// RetryPending carries waiting question cards through the same sender as their first attempt.
// Other pages and history stay Python's. Each event is read again under the seat's lock, then
// the outbox's: an answer or a competing sender may have retired or delivered it while we waited.
func RetryPending(said func(string) (string, any), errOut io.Writer) (bool, error) {
	if !config.Listable(outbox()) {
		return false, nil
	}
	for _, path := range config.Glob(outbox(), "*.json") {
		event, err := readObject(path)
		if err != nil || event == nil {
			return false, err
		}
		if retrySettled(event) {
			continue
		}
		if !retryQuestion(event) {
			return false, nil
		}
		carried := true
		err = Held(context.Background(), event.Str("session"), func(current string) error {
			held, err := holdOutbox()
			if err != nil {
				return err
			}
			defer held.Close()
			event, err := readObject(path)
			if err != nil || event == nil || retrySettled(event) {
				return err
			}
			if !retryQuestion(event) || !UnansweredQuestion(current) {
				carried = false
				return nil
			}
			word, _ := said(current)
			if word == "working" {
				return nil // its question stands through independent work; its stop sends it
			}
			if word != "needs you" {
				carried = false
				return nil
			}
			_, err = attempt(event, errOut)
			return err
		})
		if err != nil || !carried {
			return carried, err
		}
	}
	return true, nil
}

func retrySettled(event *run.Object) bool {
	return event.Str("status") == "delivered" || event.Str("status") == "disabled" || event.Str("status") == "held"
}

func retryQuestion(event *run.Object) bool {
	at, dated := finite(event.Get("created_at"))
	return event.Str("session") != "" && event.Str("kind") == "needs" && event.Truthy("episode") &&
		strings.HasPrefix(event.Str("source"), "card:") && dated && at >= installedAt() &&
		(event.Str("status") == "pending" || event.Str("status") == "blocked")
}
