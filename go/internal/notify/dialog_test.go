//go:build unix

package notify

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestADialogCardsOnceAfterTheQuestionWait(t *testing.T) {
	_, write := questionHome(t)
	file := run.Fields("state", "asking", "word", "needs you", "reason", "PermissionRequest", "word_since", 100)
	write(seatFile("seat", "acme", "json"), run.Line(file))
	now := 100.0
	transition := func() {
		t.Helper()
		carried, err := turnedQuestion("acme", func(string) (string, any) {
			return "needs you", run.Float(100)
		}, func() float64 { return now }, cardWait, io.Discard)
		if !carried || err != nil {
			t.Fatal(carried, err)
		}
	}
	if !UnansweredDialog("acme") {
		t.Fatal("a standing dialog had typed answers to act on")
	}
	transition()
	card, _ := readObject(seatFile("card", "acme", "json"))
	if card == nil || card.Truthy("sent") {
		t.Fatal(run.Line(card))
	}
	now += cardWait
	transition()
	transition()
	card, _ = readObject(seatFile("card", "acme", "json"))
	pages, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
	if !card.Truthy("sent") || len(pages) != 1 {
		t.Fatal(run.Line(card), pages)
	}
	if _, err := os.Stat(seatFile("notify", "acme", "json")); !os.IsNotExist(err) {
		t.Fatal("a screen dialog created a hook notice", err)
	}
}

func TestADialogHandsAnswersAndOtherWordsBack(t *testing.T) {
	for _, kind := range []string{"working", "ended question", "legacy ended question", "typed answer"} {
		t.Run(kind, func(t *testing.T) {
			home, write := questionHome(t)
			file := run.Fields("state", "asking", "word", "needs you", "reason", "Which branch?", "word_since", 100,
				"unasked", run.Fields("questions", []any{run.Fields("text", "Which branch?", "at", 100)}))
			switch kind {
			case "working":
				file.Set("state", "working")
			case "ended question":
				file.Dict("unasked").List("questions")[0].(*run.Object).Set("ended", 101)
			case "legacy ended question":
				file.Set("unasked", run.Fields("text", "Which branch?", "at", 100, "ended", 101))
			case "typed answer":
				write(filepath.Join(home, ".claude", "projects", "-code-acme", "conv-acme.jsonl"),
					`{"type":"user","timestamp":"2026-11-01T00:00:00Z","message":{"role":"user","content":"main"}}`+"\n")
			}
			write(seatFile("seat", "acme", "json"), run.Line(file))
			if UnansweredDialog("acme") {
				t.Fatal("a changed dialog was held open")
			}
			if carried, err := TurnedQuestion("acme", func(string) (string, any) { return "needs you", run.Float(100) }, io.Discard); carried || err != nil {
				t.Fatal(carried, err)
			}
			if _, err := os.Stat(outbox()); !os.IsNotExist(err) {
				t.Fatal("a changed dialog paged the owner", err)
			}
		})
	}
}
