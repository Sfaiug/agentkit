package notify

import (
	"context"
	"fmt"
	"io"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// RetryPending carries waiting cards through the same sender as their first attempt.
// Each event is read again under the seat's lock, then the outbox's: an answer or
// a competing sender may have retired or delivered it while we waited. A dry one
// takes no lock and acts on nothing: of each event it carries it says through log
// what Python's dry tick says. An event Go cannot read is Python's to warn of.
func RetryPending(said func(string) (string, any), dry bool, log func(string), errOut io.Writer) (bool, error) {
	if !config.Listable(outbox()) {
		return false, nil
	}
	for _, path := range config.Glob(outbox(), "*.json") {
		event, err := readObject(path)
		if err != nil || event == nil {
			return false, nil
		}
		// a page about no seat is tried again by asking for it again (Page)
		if retrySettled(event) || event.Has("session") && !event.Truthy("session") {
			continue
		}
		if !retryCard(event) && !retryHistory(event) {
			return false, nil
		}
		carried := true
		err = retryHeld(dry, event.Str("session"), func(current string) error {
			event, err := readObject(path)
			if err != nil || event == nil || retrySettled(event) {
				return err
			}
			act, err := retryAct(event, current, said, errOut)
			if err != nil {
				return err
			}
			if act == nil {
				carried = false
				return nil
			}
			if dry {
				log(fmt.Sprintf("would retry notification %s (%s)", run.Text(event.Get("id")), run.Text(event.Get("status"))))
				return nil
			}
			return act()
		})
		if err != nil || !carried {
			return carried, err
		}
	}
	return true, nil
}

// retryHeld runs fn with the seat's name now, holding its typing lock and then the outbox's; a
// dry retry takes neither, as their files are writes.
func retryHeld(dry bool, session string, fn func(current string) error) error {
	if dry {
		current, _, err := config.ResolveSession(session)
		if err != nil {
			return err
		}
		return fn(current)
	}
	return Held(context.Background(), session, func(current string) error {
		held, err := holdOutbox()
		if err != nil {
			return err
		}
		defer held.Close()
		return fn(current)
	})
}

// retryAct is what the retry does with an unsettled event of the seat named current: nothing
// where Python carries it.
func retryAct(event *run.Object, current string, said func(string) (string, any), errOut io.Writer) (func() error, error) {
	if retryHistory(event) {
		return func() error { return dropHistory(event) }, nil
	}
	seat, err := readObject(seatFile("seat", current, "json"))
	if err != nil {
		return nil, err
	}
	if seat != nil && seat.Truthy("closed_by_owner") {
		return func() error {
			run.SetAll(event, "status", "disabled", "error", "its seat was closed by the owner", "next_attempt", nil)
			return writeEvent(event)
		}, nil
	}
	send := func() error {
		_, err := attempt(event, errOut)
		return err
	}
	if !retryCard(event) {
		return nil, nil
	}
	if event.Str("kind") == "done" {
		return send, nil
	}
	if !UnansweredQuestion(current) && (seat == nil || seat.Str("state") != "asking" || !UnansweredDialog(current)) {
		return nil, nil
	}
	switch word, _ := said(current); word {
	case "working":
		return stand, nil // its question stands through independent work; its stop sends it
	case "needs you":
		return send, nil
	}
	return nil, nil
}

func stand() error { return nil }

func retrySettled(event *run.Object) bool {
	return event.Str("status") == "delivered" || event.Str("status") == "disabled" || event.Str("status") == "held"
}
