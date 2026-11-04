//go:build unix

package tick

import (
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func busyEndingSeat(t *testing.T, ak string) {
	t.Helper()
	put(t, filepath.Join(ak, "state", "session-acme.json"), `{"orchestrator":"opus"}`)
	bin := t.TempDir()
	put(t, filepath.Join(bin, "tmux"), "#!/bin/sh\ncase \" $* \" in *list-sessions*) printf 'acme\\t1\\n';; *list-panes*) printf '%%1 0\\n';; esac\n")
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
}

func TestTypedEndingsHandOverBeforeAnotherLineIsOffered(t *testing.T) {
	for _, state := range []string{"fail", "interrupted", "pass", "not_needed"} {
		t.Run(state, func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			busyEndingSeat(t, ak)
			dir := filepath.Join(ak, "runs", "fix-api")
			record := run.Fields("state", state, "launched_session", "acme", "finished_at", epoch(time.Now()),
				"merged", state == "pass", "handback_pending", true,
				"handback_typed", run.Fields("line", "run fix-api failed. Read result.md.", "seat", 123))
			put(t, filepath.Join(dir, "run.json"), run.Line(record))
			before := read(t, filepath.Join(dir, "run.json"))
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
			for _, row := range table(tick) {
				if row.name != "endings" {
					continue
				}
				for range 3 {
					after := false
					if tick.through([]pass{row, {"after", false, nil, func() error { after = true; return nil }}}) || after {
						t.Fatal("accepted the row while Python still owes the typed line its Enter")
					}
					if read(t, filepath.Join(dir, "run.json")) != before {
						t.Fatal("changed the receipt Python must finish")
					}
				}
			}
		})
	}
}

func TestAFreshInterruptionAfterALongWaitIsOfferedAsRecovery(t *testing.T) {
	ak, _ := idleHome(t, answers)
	busyEndingSeat(t, ak)
	dir := filepath.Join(ak, "runs", "fix-api")
	finished := epoch(time.Now().Add(-2 * time.Hour))
	record := run.Fields("state", "waiting", "launched_session", "acme", "finished_at", finished,
		"worktree", filepath.Join(ak, "wt", "fix-api"), "waiting_on", run.Fields("ref", "origin/main", "sha", "baseline"))
	put(t, filepath.Join(dir, "run.json"), run.Line(record))
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	var rows []pass
	for _, row := range table(tick) {
		if row.name == "waiting resume" || row.name == "endings" {
			rows = append(rows, row)
		}
	}
	if !tick.through(rows) {
		t.Fatal("did not offer the missing-worktree notice")
	}
	after, _ := run.Read(dir)
	if after.Str("state") != "interrupted" || !after.Truthy("handback_pending") || after.Truthy("handed_back") ||
		after.Truthy("recovery_notified") || after.Has("handback_note") || !run.Equal(after.Get("finished_at"), record.Get("finished_at")) {
		t.Fatalf("fresh recovery was lost or its earlier completion rewritten: %s", run.Line(after))
	}
}
