//go:build unix

package notify

import (
	"io"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAnOpenWorkCardWaitsThenSendsOnce(t *testing.T) {
	_, write := questionHome(t)
	write(seatFile("seat", "acme", "json"), run.Line(run.Fields("state", "at_prompt", "word", "needs you",
		"reason", "stopped with work open: Ship it", "word_since", 100)))
	now := 100.0
	transition := func() {
		t.Helper()
		carried, err := turnedNeed("acme", func(string) (string, any) { return "needs you", run.Float(100) },
			func() float64 { return now }, io.Discard)
		if !carried || err != nil {
			t.Fatal(carried, err)
		}
	}
	transition()
	card, _ := readObject(seatFile("card", "acme", "json"))
	if card == nil || card.Truthy("sent") {
		t.Fatal(card)
	}
	now += cardWait
	transition()
	transition()
	card, _ = readObject(seatFile("card", "acme", "json"))
	pages, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
	if !card.Truthy("sent") || len(pages) != 1 {
		t.Fatal(run.Line(card), pages)
	}
}
