//go:build unix

package tick

import (
	"bytes"
	"io"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// What the row does before any pick: a run a later merge replaced is settled, one resumed lately
// waits, and one whose worktree is gone is said once; a run waiting on a reviewer is Python's.
func TestTheExhaustedRowSettlesWaitsAndWarnsBeforeAnyPick(t *testing.T) {
	now, worktree := time.Unix(1_800_000_000, 0), t.TempDir()
	window := func(more ...any) *run.Object {
		return run.SetAll(run.Fields("run_id", "r", "state", "exhausted", "quota_dry", true, "title", "Fix api", "finished_at", 5,
			"worktree", worktree, "silence_minutes", 20, "ceiling_hours", 6), more...)
	}
	reviewer := run.Fields("state", "exhausted", "error", "reviewer: API/transport errors")
	for name, each := range map[string]struct {
		record, merged, want *run.Object
		said                 string
		left                 bool
	}{
		"replaced by a later merge": {record: window(), merged: run.Fields("run_id", "s", "state", "pass", "merged", true, "title", "Fix api", "finished_at", 6),
			want: window("replaced", true)},
		"resumed ten seconds ago": {record: window("exhausted_resume_at", epoch(now)-10), want: window("exhausted_resume_at", epoch(now)-10)},
		"its worktree gone": {record: window("worktree", "/nonexistent/wt"), want: window("worktree", "/nonexistent/wt", "exhausted_resume_at", epoch(now)),
			said: "WARN r is exhausted but its worktree /nonexistent/wt is gone; leaving it for an explicit resume\n"},
		"waiting on a reviewer": {record: reviewer, want: reviewer, left: true},
	} {
		t.Run(name, func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("HOME", home)
			t.Setenv("USERPROFILE", home)
			runs := filepath.Join(home, ".agentkit", "runs")
			put(t, filepath.Join(runs, "r", "run.json"), run.Line(each.record.Copy()))
			if each.merged != nil {
				put(t, filepath.Join(runs, "s", "run.json"), run.Line(each.merged))
			}
			var out bytes.Buffer
			tick := &ticking{clock: func() time.Time { return now }, log: newLog(&out, io.Discard)}
			for range 2 { // a second tick finds nothing more to do or say
				if err := tick.exhaustedResume(); (err == errLeft) != each.left {
					t.Fatalf("left %v", err)
				}
			}
			if got, _ := run.Read(filepath.Join(runs, "r")); !run.Equal(got, each.want) || out.String() != each.said {
				t.Fatalf("record %s; said %q", run.Line(got), out.String())
			}
		})
	}
}
