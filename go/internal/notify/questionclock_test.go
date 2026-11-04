//go:build unix

package notify

import (
	"io"
	"testing"

	"agentkit/internal/run"
)

func TestAQuestionWaitsFromItsAskAcrossCardTransitions(t *testing.T) {
	for _, existing := range []bool{false, true} {
		t.Run(run.Text(existing), func(t *testing.T) {
			_, write := questionHome(t)
			now, asked := 5000.0, 4700.0
			card := episode(run.NewObject(), "idle", run.Float(4400), run.Float(4400))
			if existing {
				card = episode(card, "needs you", run.Float(4700), run.Float(4700))
				asked = 4995
			}
			write(seatFile("notify", "acme", "json"), run.Line(run.Fields("kind", "needs", "text", "Which database?", "time", run.Float(asked))))
			write(seatFile("seat", "acme", "json"), `{"word":"needs you","reason":"Which database?","state":"at_prompt"}`)
			write(seatFile("card", "acme", "json"), run.Line(card))
			turn := func() *run.Object {
				t.Helper()
				if carried, err := turnedQuestion("acme", func(string) (string, any) { return "needs you", run.Float(5000) }, func() float64 { return now }, cardWait, io.Discard); !carried || err != nil {
					t.Fatal(carried, err)
				}
				card, err := readObject(seatFile("card", "acme", "json"))
				if err != nil {
					t.Fatal(err)
				}
				return card
			}
			if got := turn(); got.Truthy("sent") == existing {
				t.Fatalf("the page followed the card or publication clock: %s", run.Line(got))
			}
			if existing {
				now = asked + cardWait
				if got := turn(); !got.Truthy("sent") || got.Str("episode") != card.Str("episode") {
					t.Fatalf("a question that stood a minute was not paged in its episode: %s", run.Line(got))
				}
			}
		})
	}
}
