//go:build unix

package notify

import (
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A seat with a seat file asked for from outside: its card follows the word its ladder gives with
// the question standing, decided before anything is written.
func TestAnAskFollowsTheWordItsSeatSaysWithIt(t *testing.T) {
	for _, each := range []struct {
		name, file, card, word string
		question, known        bool
		want                   string // the card's word after, "" for none
		sent                   bool   // an event went to the outbox
	}{
		{name: "repeating it in the chat", file: `{"word":"idle"}`, word: "working", known: true, want: "working"},
		{name: "its question", file: `{"word":"idle"}`, word: "needs you", question: true, known: true, want: "needs you", sent: true},
		{name: "a question card through a turn", file: `{"word":"needs you"}`, card: `{"word":"needs you","since":50,"began":50,"episode":"e1","sent":false}`, word: "working", known: true, want: "needs you"},
		{name: "a question card at rest", file: `{"word":"needs you"}`, card: `{"word":"needs you","since":50,"began":50,"episode":"e1","sent":false}`, word: "idle", known: true, want: "idle"},
		{name: "a word Go does not read", file: `{"word":"idle"}`},
		{name: "a done", file: `{"word":"idle"}`, word: "done"},
		{name: "an ak wait the question ends", file: `{"word":"working","wait":{"kind":"pr","on":"#4"}}`, word: "needs you", question: true},
		{name: "a seat its owner closed", file: `{"word":"idle","closed_by_owner":true}`, word: "needs you", question: true},
	} {
		t.Run(each.name, func(t *testing.T) {
			_, write := questionHome(t)
			write(filepath.Join(os.Getenv("PATH"), "tmux"), "#!/bin/sh\nexit 1\n")
			write(seatFile("seat", "acme", "json"), each.file)
			if each.card != "" {
				write(seatFile("card", "acme", "json"), each.card)
				os.MkdirAll(outbox(), 0o700)
				write(filepath.Join(outbox(), cardKey("e1")+".json"), run.Line(run.Fields("id", cardKey("e1"), "status", "pending")))
			}
			_, record, err := config.ResolveSession("acme")
			if err != nil {
				t.Fatal(err)
			}
			var climbed *run.Object
			asked := func(name string, notice *run.Object, now time.Time) (string, any, bool) {
				if _, err := os.Stat(seatFile("notify", name, "json")); err == nil {
					t.Fatal("the word was read after the question was written")
				}
				climbed = notice
				return each.word, run.Float(40), each.question
			}
			before := clock()
			code, known := Ask("acme", record, "Which database?", asked, io.Discard, io.Discard)
			if code != 0 || known != each.known {
				t.Fatal(code, known)
			}
			notice := Last("acme")
			if each.known != (notice != nil) || each.known && run.Line(notice) != run.Line(climbed) {
				t.Fatalf("the notice written is not the one the word was read with: %v, %v", notice, climbed)
			}
			card, _ := readObject(seatFile("card", "acme", "json"))
			if !each.known {
				if each.card == "" && card != nil {
					t.Fatal("a card was written for an ask left to Python", card)
				}
				return
			}
			began, _ := card.Num("began")
			if card.Str("word") != each.want || began < before {
				t.Fatalf("card %v, want %s begun at the command", card, each.want)
			}
			if since, _ := card.Num("since"); each.card == "" && each.want == "working" && since != 40 {
				t.Fatalf("a new episode is dated from its word: %v", card)
			}
			if kept := card.Str("episode") == "e1"; kept != (each.card != "" && each.want == "needs you") {
				t.Fatalf("episode %v", card)
			}
			event, _ := readEvent(cardKey("e1"))
			if each.card != "" && (event.Str("status") == "disabled") != (each.want == "idle") {
				t.Fatalf("the question card retires only with its word: %v", event)
			}
			pages, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
			if sent := len(pages) > 0 && each.card == ""; sent != each.sent {
				t.Fatal("pages", pages)
			}
		})
	}
}
