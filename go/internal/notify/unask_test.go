//go:build unix

package notify

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// A retirement goes only while Go can carry it out at once: a held notice lock, or one Python left
// waiting for its next holder, hands it over with nothing written.  Carried out, only its questions
// go, the rest keeping their dates.
func TestAQuestionsRetirementGoesOnlyWhereGoCarriesItOut(t *testing.T) {
	_, write := questionHome(t)
	const stuck, own = "How should this seat go on? It stopped.", "Which schema should acme use?"
	notice := run.Fields("session", "acme", "kind", "needs", "text", stuck+also+own, "time", 100,
		"questions", []any{stuck, own}, "asked_at", run.Fields(questionKey(stuck), 90, questionKey(own), 95))
	write(seatFile("notify", "acme", "json"), run.Line(notice))
	var unkept []string
	unkeep := func(current, prefix string) error { unkept = append(unkept, current+": "+prefix); return nil }
	unchanged := func(why string) {
		t.Helper()
		if left, _ := filepath.Glob(filepath.Join(outbox(), "*.clear")); len(left) > 1 || len(unkept) != 0 || !run.Equal(Last("acme"), notice) {
			t.Fatal(why, left, unkept, run.Line(Last("acme")))
		}
	}
	held, err := lock.Wait(context.Background(), seatFile("notify", "acme", "lock"))
	if err != nil {
		t.Fatal(err)
	}
	if err := Unask("acme", "How should", unkeep); !errors.Is(err, ErrUnread) {
		t.Fatal("a held lock did not hand the retirement over", err)
	}
	held.Close()
	unchanged("a held lock wrote")
	waiting := filepath.Join(outbox(), "00000000000000000000000000000001.clear")
	write(waiting, `{"session": "acme", "prefix": "How should"}`)
	if err := Unask("acme", "How should", unkeep); !errors.Is(err, ErrUnread) {
		t.Fatal("a retirement left for Python's holder did not hand this one over", err)
	}
	unchanged("a waiting retirement wrote")
	if err := os.Remove(waiting); err != nil {
		t.Fatal(err)
	}
	if err := Unask("acme", "How should", unkeep); err != nil {
		t.Fatal(err)
	}
	after := Last("acme")
	if after == nil || !slices.Equal(Questions(after), []string{own}) || !run.Equal(after.Get("asked_at"), run.Fields(questionKey(own), 95)) {
		t.Fatal("only the retired questions were to go", run.Line(after))
	}
	if !slices.Equal(unkept, []string{"acme: How should"}) {
		t.Fatal("what the seat kept back was not retired with it", unkept)
	}
	if _, err := os.Stat(seatFile("card", "acme", "json")); !os.IsNotExist(err) {
		t.Fatal("a question still standing ended its card", err)
	}
}
