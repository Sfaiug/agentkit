//go:build unix

package notify

import (
	"io"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestANewDialogLeavesAnAnsweredQuestionCardToPython(t *testing.T) {
	for _, earlier := range []bool{false, true} {
		t.Run(run.Text(earlier), func(t *testing.T) {
			home, write := questionHome(t)
			write(seatFile("notify", "acme", "json"), run.Line(run.Fields("kind", "needs", "text", "Which branch?", "time", 100)))
			old := episode(run.NewObject(), "needs you", run.Float(100), run.Float(100))
			old.Set("sent", true)
			write(seatFile("card", "acme", "json"), run.Line(old))
			answered, err := Answered("acme", 200, nil, func(string) error { return nil })
			if !answered || err != nil {
				t.Fatal(answered, err)
			}
			notice, _ := readObject(seatFile("notify", "acme", "json"))
			if earlier {
				notice.Delete("answered_at")
				notice.Set("seen", true)
				notice.Set("earlier_answer_at", 200)
				write(seatFile("notify", "acme", "json"), run.Line(notice))
			}
			write(filepath.Join(home, ".claude", "projects", "-code-acme", "conv-acme.jsonl"),
				`{"type":"user","timestamp":"1970-01-01T00:03:20Z","message":{"role":"user","content":"main"}}`+"\n")
			write(seatFile("seat", "acme", "json"), run.Line(run.Fields("state", "asking", "word", "needs you", "reason", "PermissionRequest", "word_since", 300)))
			turn := func(now float64) (bool, error) {
				return turnedQuestion("acme", func(string) (string, any) { return "needs you", run.Float(300) }, func() float64 { return now }, cardWait, io.Discard)
			}
			for now := 400.0; now <= 600; now += 100 {
				if carried, err := turn(now); carried || err != nil {
					t.Fatal("the new dialog reused the answered question's card", carried, err)
				}
			}
			for kind, before := range map[string]*run.Object{"card": old, "notify": notice} {
				after, err := readObject(seatFile(kind, "acme", "json"))
				if err != nil || !run.Equal(before, after) {
					t.Fatal("handover changed the "+kind, err)
				}
			}
			// Once Python retires the answered episode, its replacement can page normally.
			write(seatFile("card", "acme", "json"), run.Line(episode(old, "needs you", run.Float(300), run.Float(300))))
			if carried, err := turn(700); !carried || err != nil {
				t.Fatal("a fresh dialog card was left behind", carried, err)
			}
			card, _ := readObject(seatFile("card", "acme", "json"))
			if card.Get("episode") == old.Get("episode") || !card.Truthy("sent") {
				t.Fatal(run.Line(card))
			}
		})
	}
}
