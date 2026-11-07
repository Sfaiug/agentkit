package seat

import (
	"testing"
	"time"

	"agentkit/internal/run"
	usages "agentkit/internal/usage"
)

// A wait on an account with room that nothing refused ends on a turn begun since, nothing typed;
// a turn in flight from before the wait is one ak would continue, Python's, nothing written.
func TestTheOwnersOwnTurnEndsAWaitOnAnAccountWithRoom(t *testing.T) {
	home := sandbox(t)
	now := time.Now()
	since := seconds(now) - 600
	write(t, stateFile(home, "usage.json"), run.Line(run.Fields("fetched_at", seconds(now),
		"providers", run.Fields("test", run.Fields("meters", []any{})))))
	readings, err := usages.Cached()
	if err != nil {
		t.Fatal(err)
	}
	for began, ends := range map[float64]bool{since + 60: true, since - 60: false} {
		wait := run.Fields("reason", "test out of usage until 18:59", "since", run.Float(since),
			"until", run.Float(since+4200), "continue", false)
		write(t, stateFile(home, "seat-acme.json"), run.Line(run.Fields("session", "acme", "usage_wait", wait)))
		before := stateFiles(t, home)["seat-acme.json"]
		file, err := run.ReadJSON(stateFile(home, "seat-acme.json"))
		if err != nil {
			t.Fatal(err)
		}
		live := Live{Name: "acme", Own: "claude", Record: run.Fields("orchestrator", "opus"), File: file, State: "working"}
		found := sight{state: "working", began: run.Float(began)}
		ended, carried := (Seat{Name: "acme", own: "claude"}).waitOnUsage(stateFile(home, ""), live, "opus", found, readings, now, func(string) {})
		if carried != ends {
			t.Fatalf("turn begun %+.0f s from the wait: carried=%v", began-since, carried)
		}
		if !carried {
			if after := stateFiles(t, home)["seat-acme.json"]; after != before {
				t.Fatalf("handed over after writing the seat file: %s", after)
			}
			continue
		}
		if err := ended(); err != nil {
			t.Fatal(err)
		}
		left, err := run.ReadJSON(stateFile(home, "seat-acme.json"))
		if err != nil || !left.Has("usage_wait") || left.Get("usage_wait") != nil {
			t.Fatalf("wait not ended: %v, %v", left, err)
		}
	}
}
