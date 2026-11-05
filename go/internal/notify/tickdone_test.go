//go:build unix

package notify

import (
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestNewCompletionPagesEvenWithoutAnInterveningWordChange(t *testing.T) {
	_, write := questionHome(t)
	write(seatFile("session", "acme", "json"), `{"created":1}`)
	write(seatFile("seat", "acme", "json"), `{"word":"done","reason":"Ship the release"}`)
	word := "done"
	said := func(string) (string, any) { return word, run.Float(clock()) }
	work := []any{[]any{"", "Ship the release"}}
	outcomes := func(string) ([]any, error) { return work, nil }
	turn := func(pages int) *run.Object {
		t.Helper()
		if carried, err := TurnedPlan("acme", said, outcomes); !carried || err != nil {
			t.Fatal(carried, err)
		}
		paths, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
		if len(paths) != pages {
			t.Fatalf("queued %d pages, want %d", len(paths), pages)
		}
		card, err := readObject(seatFile("card", "acme", "json"))
		if err != nil {
			t.Fatal(err)
		}
		return card
	}
	first := turn(1)
	word = "working"
	turn(1)
	word = "done"
	turn(1)
	work = []any{[]any{"", "Fix the docs"}}
	last := turn(2)
	if last.Str("episode") == first.Str("episode") || !last.Truthy("sent") ||
		!run.Equal(last.Dict("completed").Get("outcomes"), []any{[]any{"", "Fix the docs"}, []any{"", "Ship the release"}}) {
		t.Fatal("new work did not retain the earlier completion", run.Line(last))
	}
	work = []any{[]any{"", "Ship the release"}}
	turn(2)
}
