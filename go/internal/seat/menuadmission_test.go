package seat

import (
	"fmt"
	"reflect"
	"slices"
	"testing"
	"time"

	"agentkit/internal/tmux"
)

func TestMenuLeavesParkedRunDecisionsToPython(t *testing.T) {
	for _, each := range []struct {
		name   string
		fields map[string]any
		known  bool
	}{
		{"expired merge wait", map[string]any{"state": "waiting", "finished_at": seconds(moment) - 172800,
			"waiting_on": map[string]any{"ref": "origin/main", "sha": "abc123"}}, false},
		{"scheduled retry", map[string]any{"state": "error", "finished_at": seconds(moment) - 10, "error_retry_at": seconds(moment) + 60}, true},
		{"admitted merge wait", map[string]any{"state": "waiting", "finished_at": seconds(moment) - 10,
			"waiting_on": map[string]any{"ref": "origin/main", "sha": "abc123"}}, true},
		{"landing line", map[string]any{"state": "waiting", "finished_at": seconds(moment) - 172800,
			"waiting_on": map[string]any{"line": "acme"}}, true},
	} {
		for _, live := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/live=%v", each.name, live), func(t *testing.T) {
				home := sandbox(t)
				record(t, home, "acme", nil)
				if live {
					drawn(t, home, "acme", prompting)
				}
				runRecord(t, home, "going", each.fields)
				found, known := Menu(moment)
				if known != each.known || known && (len(found.Seats) != 1 || found.Seats[0].Word != "working") {
					t.Fatalf("known %v, want %v: %+v", known, each.known, found.Seats)
				}
			})
		}
	}
}

func TestMenuKeepsBackgroundRunsUnderRetainedDeadPanes(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	drawn(t, home, "acme", prompting)
	if _, err := tmux.Ask(tmux.Own(), "set-option", "-t", "=acme:", "remain-on-exit", "on", ";",
		"respawn-pane", "-k", "-t", "=acme:", "true"); err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(10 * time.Second); !slices.Contains(tmux.Dead(tmux.Own()), "acme"); time.Sleep(10 * time.Millisecond) {
		if time.Now().After(deadline) {
			t.Fatal("pane did not exit")
		}
	}
	runRecord(t, home, "going", map[string]any{"state": "running", "step": "reviewer"})
	found, known := Menu(moment)
	if !known || len(found.Seats) != 1 || !found.Seats[0].held || found.Seats[0].live || found.Seats[0].Word != "working" {
		t.Fatalf("known %v: %+v", known, found.Seats)
	}
	if got := found.Seats[0].Tasks(); !reflect.DeepEqual(got, []Task{{Stage: 1, Moving: true}}) {
		t.Fatal(got)
	}
}
