//go:build unix

package notify

import (
	"io"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A seat first seen on a stalled run's need has no moment for its word: its card's episode begins
// at the first transition that reads it, keeps that moment, and goes out once after the wait.
func TestAnUndatedNeedIsCardedFromItsFirstTransition(t *testing.T) {
	_, write := questionHome(t)
	reason := "run fix-api stalled: resume it with `ak run resume fix-api`"
	write(seatFile("seat", "acme", "json"), run.Line(run.Fields("state", "at_prompt", "word", "needs you",
		"reason", reason, "word_since", nil)))
	now := 100.0
	transition := func() *run.Object {
		t.Helper()
		carried, err := turnedNeed("acme", func(string) (string, string, any) { return "needs you", reason, nil },
			func() float64 { return now }, io.Discard)
		if !carried || err != nil {
			t.Fatal(carried, err)
		}
		card, _ := readObject(seatFile("card", "acme", "json"))
		return card
	}
	if card := transition(); number(card, "since") != 100 || card.Truthy("sent") {
		t.Fatal(run.Line(card))
	}
	now += cardWait - 1
	if card := transition(); number(card, "since") != 100 || card.Truthy("sent") {
		t.Fatal(run.Line(card))
	}
	now++
	transition()
	card := transition()
	pages, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
	if number(card, "since") != 100 || !card.Truthy("sent") || len(pages) != 1 {
		t.Fatal(run.Line(card), pages)
	}
}
