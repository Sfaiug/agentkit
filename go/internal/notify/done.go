package notify

import (
	"io"

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
