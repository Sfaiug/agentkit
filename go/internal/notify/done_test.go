package notify

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestADoneQueuesItsWorkOnceEvenWhenItsCardIsLost(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("AK_NOTIFY_SINK", "dry-run")
	t.Setenv("AGENTKIT_DISCORD_USER_ID", "")
	t.Setenv("PATH", t.TempDir())
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	for kind, text := range map[string]string{"session": `{"created":1}`, "seat": `{"word":"done","reason":"API ships"}`} {
		if err := os.WriteFile(seatFile(kind, "acme", "json"), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
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
