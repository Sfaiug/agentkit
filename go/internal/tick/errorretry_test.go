//go:build unix

package tick

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestOneRecordThatCannotBeWrittenKeepsNoOtherErrorFromItsRetry(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	now := time.Now()
	runs := filepath.Join(home, ".agentkit", "runs")
	first := filepath.Join(runs, "a-error")
	put(t, filepath.Join(first, "run.json"), run.Line(run.Fields("state", "error", "error_retry_at", 1, "error_retries", 1)))
	if err := os.Chmod(first, 0o500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(first, 0o700) })
	later := filepath.Join(runs, "z-error")
	put(t, filepath.Join(later, "run.json"), run.Line(run.Fields("state", "error", "scratch", true, "worktree", t.TempDir(),
		"rounds", 3, "finished_at", epoch(now), "launched_session", "acme")))
	put(t, filepath.Join(later, "task.md"), "## Done when\n```bash\ntrue\n```\n")
	put(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), "{}")
	var out bytes.Buffer
	tick := &ticking{clock: func() time.Time { return now }, log: newLog(&out, io.Discard)}
	var row []pass
	for _, each := range table(tick) {
		if each.name == "error retry" {
			row = append(row, each)
		}
	}
	carried := tick.through(row)
	record, err := run.Read(later)
	if err != nil {
		t.Fatal(err)
	}
	if !carried || !record.Has("error_retry_at") || !strings.Contains(out.String(), "WARN cannot check run a-error: ") {
		t.Fatalf("carried %v, %s; said %q", carried, run.Line(record), out.String())
	}
}
