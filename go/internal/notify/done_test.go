package notify

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestADoneQueuesItsWorkOnceEvenWhenItsCardIsLost(t *testing.T) {
	_, write := questionHome(t)
	// a seat as launched: its done's row is read from the conversation its harness keeps
	write(seatFile("session", "acme", "json"), `{"orchestrator":"opus","cwd":"/code/acme","conversation":"conv-acme","created":1}`)
	write(seatFile("seat", "acme", "json"), `{"word":"done","reason":"API ships"}`)
	said := func(string) (string, any) { return "done", run.Float(clock()) }
	work := func(string) ([]any, error) { return []any{[]any{"acme/api", "API ships"}}, nil }
	cardPath := seatFile("card", "acme", "json")
	for range 2 {
		if carried, err := TurnedPlan("acme", said, work); !carried || err != nil {
			t.Fatalf("carried=%v: %v", carried, err)
		}
		before, _ := os.ReadFile(cardPath)
		if carried, err := TurnedPlan("acme", said, work); !carried || err != nil {
			t.Fatal(carried, err)
		}
		if after, _ := os.ReadFile(cardPath); string(after) != string(before) {
			t.Fatal("a settled done rewrote its card")
		}
		events, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
		if len(events) != 1 {
			t.Fatalf("queued %d events", len(events))
		}
		// went out or was turned away: a held done would neither deliver nor retry
		event, _ := run.ReadJSON(events[0])
		status := event.Str("status")
		if event.Str("kind") != "done" || status != "delivered" && status != "disabled" || event.Dict("payload").Str("content") != "✅ Done · acme" {
			t.Fatal(run.Line(event))
		}
		if err := os.Remove(cardPath); err != nil {
			t.Fatal(err)
		}
	}
}
