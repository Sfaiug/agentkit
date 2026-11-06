package notify

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAStandingQuestionKeepsItsCardThroughWork(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	write := func(name, data string) {
		if err := os.WriteFile(filepath.Join(state(), name), []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	asked := `{"kind": "needs", "text": "Which schema?", "time": 1000`
	card := `{"word": "needs you", "since": 1000, "began": 1000, "episode": "e", "sent": true}`
	for name, each := range map[string]struct {
		notice, card, word string
		kept               bool
	}{
		"at work":            {asked + "}", card, "working", true},
		"back at its prompt": {asked + "}", card, "idle", false},
		"answered":           {asked + `, "answered_at": 2000}`, card, "working", false},
		"a watcher's alert":  {asked + `, "watcher": true}`, card, "working", false},
		"carded working":     {asked + "}", `{"word": "working", "since": 1000}`, "working", false},
	} {
		t.Run(name, func(t *testing.T) {
			write("notify-acme.json", each.notice)
			write("card-acme.json", each.card)
			kept, err := TurnedKeptQuestion("acme", func(string) (string, any) { return each.word, 3000 })
			after, _ := os.ReadFile(filepath.Join(state(), "card-acme.json"))
			if kept != each.kept || err != nil || string(after) != each.card {
				t.Fatalf("kept %v, %v: %s", kept, err, after)
			}
		})
	}
}
