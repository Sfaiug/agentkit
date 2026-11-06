//go:build unix

package notify

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// A need is carded as the ladder words it now, whatever the look published before a row moved it:
// here the ending it was being told, which the endings row has typed in since.
func TestAnOpenWorkCardWaitsThenSendsOnce(t *testing.T) {
	for published, reason := range map[string]string{
		"needs you": "stopped with work open: Ship it",
		"working":   "telling it how run fix-api ended",
	} {
		t.Run(published, func(t *testing.T) {
			_, write := questionHome(t)
			write(seatFile("seat", "acme", "json"), run.Line(run.Fields("state", "at_prompt", "word", published,
				"reason", reason, "word_since", 100)))
			now := 100.0
			transition := func() {
				t.Helper()
				carried, err := turnedNeed("acme", func(string) (string, string, any) {
					return "needs you", "stopped with work open: Ship it", run.Float(100)
				}, func() float64 { return now }, io.Discard)
				if !carried || err != nil {
					t.Fatal(carried, err)
				}
			}
			transition()
			card, _ := readObject(seatFile("card", "acme", "json"))
			if card == nil || card.Truthy("sent") {
				t.Fatal(card)
			}
			now += cardWait
			transition()
			transition()
			card, _ = readObject(seatFile("card", "acme", "json"))
			pages, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
			if !card.Truthy("sent") || len(pages) != 1 {
				t.Fatal(run.Line(card), pages)
			}
			if page, _ := os.ReadFile(pages[0]); !strings.Contains(string(page), "stopped with work open: Ship it") {
				t.Fatalf("the page is not the need the ladder words now: %s", page)
			}
		})
	}
}
