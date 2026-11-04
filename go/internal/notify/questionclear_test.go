//go:build unix

package notify

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAQuestionRetirementUnderTheLockHandsOverWithoutPaging(t *testing.T) {
	_, write := questionHome(t)
	notice := `{"kind":"needs","text":"Which database?","time":100}`
	write(seatFile("notify", "acme", "json"), notice)
	write(seatFile("seat", "acme", "json"), `{"word":"needs you","reason":"Which database?","state":"at_prompt"}`)
	path := filepath.Join(outbox(), "00000000000000000000000000000001.clear")
	clear := `{"session":"acme","prefix":"Which database?"}`
	carried, err := turnedQuestion("acme", func(string) (string, any) {
		// A hook may leave its retirement while the tick holds the notice lock.
		write(path, clear)
		return "needs you", run.Float(100)
	}, func() float64 { return 5000 }, io.Discard)
	if carried || err != nil {
		t.Fatal(carried, err)
	}
	for file, want := range map[string]string{path: clear, seatFile("notify", "acme", "json"): notice} {
		if got, err := os.ReadFile(file); err != nil || string(got) != want {
			t.Fatalf("handover changed %s: %s, %v", file, got, err)
		}
	}
	if _, err := os.Stat(seatFile("card", "acme", "json")); !os.IsNotExist(err) {
		t.Fatal("a withdrawn question got a card")
	}
	if events, err := filepath.Glob(filepath.Join(outbox(), "*.json")); err != nil || len(events) != 0 {
		t.Fatal("a withdrawn question queued a page", events, err)
	}
}
