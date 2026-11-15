package livefollow

import (
	"os"
	"slices"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// Only the write that first records a run merged with a `health:` hands it to its project's
// follower, and only while the run awaits that proof: one inside its window, not live yet.  With
// the follower lock held, it goes on the list the follower takes.
func TestAMergeIsHandedOnAsItFirstAwaitsItsHealth(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	if err := os.MkdirAll(run.Runs(), 0o700); err != nil {
		t.Fatal(err)
	}
	repo := "/src/api"
	held, err := lock.Try(Path(repo, "follower"))
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	now := float64(time.Now().Unix())
	health := run.Fields("command", "live-check")
	record := func(pairs ...any) *run.Object { return run.Fields(append([]any{"repo", repo}, pairs...)...) }
	for name, each := range map[string]struct {
		before, after *run.Object
		handed        bool
	}{
		"its merge, not yet finished": {record(), record("merged", true, "health", health), true},
		"its health found late":       {record("merged", true), record("merged", true, "health", health, "finished_at", now), true},
		"a write after its merge":     {record("merged", true, "health", health), record("merged", true, "health", health, "finished_at", now), false},
		"a merge with no health":      {record(), record("merged", true, "health", run.NewObject()), false},
		"a merge gone live":           {record(), record("merged", true, "health", health, "live_at", now), false},
		"a merge past its window":     {record(), record("merged", true, "health", health, "finished_at", now-4*3600), false},
		"a merge of no project":       {run.NewObject(), run.Fields("merged", true, "health", health), false},
	} {
		t.Run(name, func(t *testing.T) {
			Merged(run.Runs()+"/20261106-1200-api-one", each.before, each.after)
			if runs, err := Runs(repo, ""); err != nil || slices.Equal(runs, []string{"20261106-1200-api-one"}) != each.handed {
				t.Errorf("handed %q, %v", runs, err)
			}
		})
	}
}
