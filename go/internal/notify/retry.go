package notify

import (
	"context"
	"io"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// RetryPending carries waiting cards through the same sender as their first attempt.
// Each event is read again under the seat's lock, then the outbox's: an answer or
// a competing sender may have retired or delivered it while we waited.
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
		if !retryCard(event) && !retryHistory(event) {
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
			if retryHistory(event) {
				return dropHistory(event)
			}
			seat, err := readObject(seatFile("seat", current, "json"))
			if err != nil {
				return err
			}
			if seat != nil && seat.Truthy("closed_by_owner") {
				event.Set("status", "disabled")
				event.Set("error", "its seat was closed by the owner")
				event.Set("next_attempt", nil)
				return writeEvent(event)
			}
			if !retryCard(event) {
				carried = false
				return nil
			}
			if event.Str("kind") == "done" {
				_, err = attempt(event, errOut)
				return err
			}
			if !UnansweredQuestion(current) && (seat == nil || seat.Str("state") != "asking" || !UnansweredDialog(current)) {
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
