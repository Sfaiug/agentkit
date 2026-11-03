package notify

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestDoneKeepsCoverageAfterPlanCleanupAndLostCard(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("AK_NOTIFY_SINK", "dry-run")
	t.Setenv("AGENTKIT_DISCORD_USER_ID", "")
	t.Setenv("PATH", t.TempDir())
	os.MkdirAll(outbox(), 0o700)
	for kind, text := range map[string]string{"session": `{"created":1}`, "seat": `{"word":"done","reason":"API ships"}`} {
		os.WriteFile(seatFile(kind, "acme", "json"), []byte(text), 0o600)
	}
	previous := `{"id":"previous","kind":"done","session":"acme","status":"delivered","completion":{"created":1,"outcomes":[["","API ships"],["","Web ships"]]}}`
	os.WriteFile(filepath.Join(outbox(), "previous.json"), []byte(previous), 0o600)
	work := func(string) ([]any, error) { return []any{[]any{"", "API ships"}}, nil }
	said := func(string) (string, any) { return "done", run.Float(clock()) }
	if carried, err := TurnedPlan("acme", said, work); !carried || err != nil {
		t.Fatal(carried, err)
	}
	events, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
	if len(events) != 1 {
		t.Fatalf("plan cleanup replayed delivered work: %d events", len(events))
	}
	card, _ := run.ReadJSON(seatFile("card", "acme", "json"))
	if !card.Truthy("sent") || len(card.Dict("completed").List("outcomes")) != 2 {
		t.Fatal("prior completion coverage was lost", run.Line(card))
	}
	if after, _ := os.ReadFile(events[0]); string(after) != previous {
		t.Fatal("completion receipt was rewritten")
	}
}
