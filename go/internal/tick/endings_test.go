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

func TestEndingsOfferPendingDecisionsAndInterruptionsAtTheirOwnRow(t *testing.T) {
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "state", "session-acme.json"), `{"orchestrator":"opus"}`)
	tmux := filepath.Join(t.TempDir(), "tmux")
	put(t, tmux, "#!/bin/sh\ncase \" $* \" in *list-sessions*) printf 'acme\\t1\\n';; *list-panes*) printf '%%1 0\\n';; esac\n")
	if err := os.Chmod(tmux, 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", filepath.Dir(tmux)+string(os.PathListSeparator)+os.Getenv("PATH"))
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	for _, state := range []string{"fail", "interrupted"} {
		dir := filepath.Join(ak, "runs", state)
		record := run.Fields("state", state, "launched_session", "acme", "finished_at", epoch(time.Now()),
			"notification_pending", true, "rounds", 1, "round_summaries", []any{run.Fields("round", 1)})
		if !tick.through([]pass{
			{"before", false, nil, func() error { put(t, filepath.Join(dir, "run.json"), run.Line(record)); return nil }},
			{"endings", false, tick.endingsIdle, tick.endings},
		}) {
			t.Fatal("ending was not offered at its own turn")
		}
		after, _ := run.Read(dir)
		if !after.Truthy("handback_pending") || after.Truthy("handed_back") || after.Truthy("recovery_notified") {
			t.Fatalf("busy seat lost its pending %s: %s", state, run.Line(after))
		}
		before := read(t, filepath.Join(dir, "run.json"))
		if err := tick.endings(); err != nil || before != read(t, filepath.Join(dir, "run.json")) {
			t.Fatalf("busy seat's pending mark was rewritten: %v", err)
		}
	}
}
