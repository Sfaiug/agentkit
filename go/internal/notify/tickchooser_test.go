//go:build unix

package notify

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAChooserWaitsForInputAndDepartureThenPagesOnce(t *testing.T) {
	_, write := questionHome(t)
	write(seatFile("seat", "acme", "json"), `{"word":"needs you","state":"asking","reason":"Pick one","word_since":900}`)
	// questionHome puts just its fake tools on PATH.
	tmux := filepath.Join(os.Getenv("PATH"), "tmux")
	activity := func(attached, last string) {
		write(tmux, "#!/bin/sh\nprintf '"+attached+"\\t"+last+"\\n'\n")
	}
	now := 1000.0
	said := func(string) (string, any) { return "needs you", run.Float(900) }
	turn := func(want bool) *run.Object {
		t.Helper()
		if carried, err := turnedQuestion("acme", said, func() float64 { return now }, cardWait, io.Discard); !carried || err != nil {
			t.Fatal(carried, err)
		}
		card, err := readObject(seatFile("card", "acme", "json"))
		if err != nil || card.Truthy("sent") != want {
			t.Fatalf("card=%v, error=%v", card, err)
		}
		return card
	}
	activity("0", "990")
	first := turn(false)
	now = 1050
	activity("1", "990")
	turn(false)
	now = 1100
	activity("0", "990")
	turn(false)
	now = 1159
	turn(false)
	now = 1160
	card := turn(true)
	if card.Str("episode") != first.Str("episode") {
		t.Fatal("the held chooser lost its episode")
	}
	turn(true)
	paths, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
	if len(paths) != 1 {
		t.Fatalf("queued %d pages", len(paths))
	}
	event, err := readObject(paths[0])
	if err != nil || event.Dict("payload").Str("content") != "🙋 Needs you · acme" {
		t.Fatal(event, err)
	}
}

func TestAnAnsweredChooserLeavesItsNextEpisodeToPython(t *testing.T) {
	_, write := questionHome(t)
	write(seatFile("seat", "acme", "json"), `{"word":"needs you","state":"asking","reason":"Pick one","word_since":100}`)
	card := episode(run.NewObject(), "needs you", run.Float(100), run.Float(100))
	card.Set("answered_at", 200)
	before := run.Line(card)
	write(seatFile("card", "acme", "json"), before)
	if carried, err := TurnedQuestion("acme", func(string) (string, any) { return "needs you", run.Float(100) }, io.Discard); carried || err != nil {
		t.Fatal(carried, err)
	}
	if after, err := os.ReadFile(seatFile("card", "acme", "json")); err != nil || string(after) != before {
		t.Fatal("the answer's episode was changed", err)
	}
	if paths, _ := filepath.Glob(filepath.Join(outbox(), "*.json")); len(paths) != 0 {
		t.Fatal("an answered episode paged", paths)
	}
}
