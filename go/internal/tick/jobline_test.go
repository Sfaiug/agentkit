//go:build unix

package tick

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/job"
	"agentkit/internal/run"
)

// A long line Go leaves to Python, typed past a draft by Python's editor or for a seat gone, is
// left before its ending.txt is written: Python writes its own.
func TestAJobsLongLineLeftToPythonWritesNothing(t *testing.T) {
	for _, pane := range []bool{true, false} {
		home := t.TempDir()
		t.Setenv("HOME", home)
		t.Setenv("AGENTKIT_SESSION", "")
		bin, dir := filepath.Join(home, "bin"), filepath.Join(home, ".agentkit", "jobs", "acme")
		os.MkdirAll(bin, 0o700)
		os.MkdirAll(dir, 0o700)
		// no tmux server holds a session by that name
		os.WriteFile(filepath.Join(bin, "tmux"), []byte("#!/bin/sh\nexit 1\n"), 0o700)
		t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
		line := "job acme: a.md: BLOCKED: " + strings.Repeat("fixtures/api.json is never named ", 100) +
			". Result: " + filepath.Join(dir, "log.txt") + ". Decide the next step."
		receipt := run.Fields("job_id", "acme", "seat", "omega", "finished_at", 1, "handback_pending", line)
		if pane {
			receipt.Set("handback_typed", run.Fields("line", line, "seat", 1000, "pane", "%1"))
		}
		job.Save(dir, receipt)
		if err := (&ticking{log: newLog(io.Discard, io.Discard)}).jobHandback(dir); !errors.Is(err, errLeft) {
			t.Fatalf("the line was not left to Python: %v", err)
		}
		if _, err := os.Stat(filepath.Join(dir, "ending.txt")); !os.IsNotExist(err) {
			t.Fatalf("a line left to Python wrote ending.txt: %v", err)
		}
	}
}
