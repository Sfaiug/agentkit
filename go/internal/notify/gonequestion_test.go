//go:build unix

package notify

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAnAttachedDeadPaneDoesNotHoldItsDueQuestionPage(t *testing.T) {
	for _, each := range []struct {
		name, dead, activity string
		sent                 bool
	}{
		{"live", "0", "4700", false},
		{"dead", "1", "4700", true},
		{"dead with recent input", "1", "4990", false},
	} {
		t.Run(each.name, func(t *testing.T) {
			_, write := questionHome(t)
			t.Setenv("DEAD", each.dead)
			t.Setenv("ACTIVITY", each.activity)
			write(filepath.Join(os.Getenv("PATH"), "tmux"), `#!/bin/sh
case "$*" in
  *list-panes*) printf 'acme\t%s\n' "$DEAD" ;;
  *) printf '1\t%s\n' "$ACTIVITY" ;;
esac
`)
			write(seatFile("notify", "acme", "json"), `{"kind":"needs","text":"Which database?","time":4700}`)
			reason := "Which database?"
			if each.dead == "1" {
				reason = "session closed: press 1 to reopen"
			}
			write(seatFile("seat", "acme", "json"), run.Line(run.Fields("word", "needs you", "reason", reason)))
			write(seatFile("card", "acme", "json"), run.Line(run.Fields(
				"word", "needs you", "since", 4700, "began", 4700, "episode", "question", "sent", false)))
			if carried, err := turnedQuestion("acme", func(string) (string, any) { return "needs you", nil },
				func() float64 { return 5000 }, cardWait, io.Discard); !carried || err != nil {
				t.Fatal(carried, err)
			}
			card, err := readObject(seatFile("card", "acme", "json"))
			if err != nil || card.Truthy("sent") != each.sent {
				t.Fatalf("sent=%v: %v %s", each.sent, err, run.Line(card))
			}
			event, err := readEvent(cardKey("question"))
			if err != nil || (event != nil) != each.sent {
				t.Fatal("the due card and its outbox disagree", event, err)
			}
		})
	}
}
