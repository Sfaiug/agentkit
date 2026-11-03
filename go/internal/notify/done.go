package notify

import (
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func Turned(name string, said func(string) (string, any)) (bool, error) {
	return turned(name, said, nil)
}

// TurnedPlan also carries a done card from verified plan outcomes. History, deferred outcomes
// and work changed since an earlier done remain Python's, read before any write.
func TurnedPlan(name string, said func(string) (string, any), outcomes func(string) ([]any, error)) (bool, error) {
	return turned(name, said, func(name string, card *run.Object, since any) (bool, error) {
		if !run.Historyless() {
			return false, nil
		}
		work, err := outcomes(name)
		if err != nil {
			return false, nil
		}
		record, err := run.ReadJSON(seatFile("session", name, "json"))
		if err != nil || record == nil {
			return false, nil
		}
		var completion any
		if record.Get("created") != nil && len(work) > 0 {
			completion = run.Fields("created", record.Get("created"), "outcomes", work)
		}
		if card.Has("completed") && !run.Equal(card.Get("completed"), completion) {
			return false, nil
		}
		if card.Str("word") == "done" && (card.Truthy("sent") || completion == nil && card.Str("closed") == "Done") {
			return true, nil
		}
		if _, ok := finite(since); !ok {
			since = run.Float(clock())
		}
		newWord := card.Str("word") != "done"
		if newWord {
			card = episode(card, "done", since, since)
		}
		seat, _ := run.ReadJSON(seatFile("seat", name, "json"))
		if number(card, "began") < installedAt() || seat != nil && seat.Truthy("closed_by_owner") {
			if newWord {
				return true, writeCard(name, card)
			}
			return true, nil
		}
		card.Set("closed", "Done")
		if completion == nil {
			return true, writeCard(name, card)
		}
		covered, err := doneCovered(name, completion)
		if err != nil {
			return false, err
		}
		if covered {
			run.SetAll(card, "sent", true, "completed", completion)
			return true, writeCard(name, card)
		}
		return true, sendDone(name, card, completion)
	})
}

func sendDone(name string, card *run.Object, completion any) error {
	seat, err := run.ReadJSON(seatFile("seat", name, "json"))
	if err != nil {
		return err
	}
	if seat == nil {
		return errNotObject
	}
	_, err = sendEpisode(name, "done", card, run.Fields("text", seat.Str("reason")), completion, io.Discard)
	return err
}

// A card can be lost while its queued completion survives, including through a seat's rename.
func doneCovered(name string, completion any) (bool, error) {
	entries, err := os.ReadDir(outbox())
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	for _, entry := range entries {
		if !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		event, err := run.ReadJSON(filepath.Join(outbox(), entry.Name()))
		if err != nil || event == nil || event.Str("kind") != "done" || !run.Equal(event.Get("completion"), completion) {
			continue
		}
		current, _, err := config.ResolveSession(event.Str("session"))
		if err == nil && current == name {
			return true, nil
		}
	}
	return false, nil
}

// QuietOutbox leaves only unsettled events to Python's retry pass.
func QuietOutbox() bool {
	entries, err := os.ReadDir(outbox())
	if os.IsNotExist(err) {
		return true
	}
	if err != nil {
		return false
	}
	for _, entry := range entries {
		if !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		event, err := run.ReadJSON(filepath.Join(outbox(), entry.Name()))
		if err != nil || event == nil || event.Str("status") != "delivered" && event.Str("status") != "disabled" {
			return false
		}
	}
	return true
}
