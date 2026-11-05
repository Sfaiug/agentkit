package notify

import (
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/run"
)

func Turned(name string, said func(string) (string, any)) (bool, error) {
	return turned(name, said, nil)
}

// TurnedPlan also carries a done card from verified plan outcomes. Deferred
// outcomes remain Python's, read before any write.
func TurnedPlan(name string, said func(string) (string, any), outcomes func(string) ([]any, error)) (bool, error) {
	return turned(name, said, func(name string, card *run.Object, word string, since any) (bool, error) {
		return planCard(name, card, word, since, outcomes)
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
