package seat

import (
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
	usages "agentkit/internal/usage"
)

// The wait is decided from the model the look follows, before its move is written: a Grok Build
// seat whose summary moves it between a spent subscription and one with room is Python's, with
// nothing written, either way, as watch.lock was taken or not ahead for the model its record named.
func TestAWaitIsDecidedFromTheModelTheLookFollows(t *testing.T) {
	for _, spent := range []string{"test", "other"} {
		t.Run(spent, func(t *testing.T) {
			root := filepath.Join(sandbox(t), ".grok")
			home := grokSummarySeat(t, root, `{"current_model_id":"grok-other","reasoning_effort":"high"}`, "")
			write(t, filepath.Join(home, ".agentkit", "config.toml"),
				grokConfig+"[models.swift]\nharness='grokbuild'\nmodel='grok-other'\neffort='high'\nprovider='other'\n[providers.other]\nmode='subscription'\n")
			write(t, stateFile(home, "usage.json"), run.Line(run.Fields("fetched_at", seconds(time.Now()), "providers",
				run.Fields(spent, run.Fields("meters", []any{}, "resets", 0, "exhausted_until", seconds(time.Now())+3600)))))
			drawn(t, home, "acme", grokTrust)
			before := stateFiles(t, home)
			if carried, err := Health("acme", func(Live) bool { return true }, func(string) {}); carried || err != nil {
				t.Fatalf("carried=%v, err=%v", carried, err)
			}
			if after := stateFiles(t, home)["seat-acme.json"]; after != before["seat-acme.json"] {
				t.Fatalf("handed over after writing the seat file: %s", after)
			}
			grokFollowed(t, home, before["session-acme.json"], "", "")
		})
	}
}

// A seat its spent subscription refused nothing is waited on only where its ladder reads the wait:
// beside its `ak wait` it is Python's, nothing written.
func TestASpentSubscriptionIsWaitedOnOnlyWhereTheLadderReadsTheWait(t *testing.T) {
	home := sandbox(t)
	write(t, stateFile(home, "usage.json"), run.Line(run.Fields("fetched_at", seconds(time.Now()),
		"providers", run.Fields("test", run.Fields("meters", []any{}, "exhausted_until", seconds(time.Now())+3600)))))
	readings, err := usages.Cached()
	if err != nil {
		t.Fatal(err)
	}
	for file, waits := range map[string]bool{`{}`: true, `{"wait": {"kind": "pr", "on": "https://github.com/acme/widget/pull/1", "at": 1}}`: false} {
		write(t, stateFile(home, "seat-acme.json"), file)
		read, err := run.ReadJSON(stateFile(home, "seat-acme.json"))
		if err != nil {
			t.Fatal(err)
		}
		live := Live{Name: "acme", Own: "claude", Record: run.Fields("orchestrator", "opus"), File: read, State: "at_prompt"}
		if _, waited := (Seat{Name: "acme", own: "claude"}).waitOnUsage(stateFile(home, ""), live, "opus", sight{}, readings, time.Now(), func(string) {}); waited != waits {
			t.Errorf("seat file %s: waits %v", file, waited)
		}
	}
}
