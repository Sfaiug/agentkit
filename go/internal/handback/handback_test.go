package handback

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

func blocked(why string) *run.Object {
	return run.Fields("state", "blocked", "error", why, "rounds", run.Number("3"), "round_summaries", []any{},
		"branch", "ak/add-retry-file")
}

func TestABlockedEndingIsToldInItsDecisionLineWhole(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	dir := filepath.Join(home, ".agentkit", "runs", "20261103-0931-add-retry-file")
	got := handbackLine(blocked("cannot be\n  done as written"), dir, true, false)
	want := "run 20261103-0931-add-retry-file BLOCKED (0 of 3): cannot be done as written. Next: rewrite the task " +
		"and relaunch it with `from: ak/add-retry-file`. Result: ~/.agentkit/runs/20261103-0931-add-retry-file/result.md"
	if got != want {
		t.Fatalf("got  %q\nwant %q", got, want)
	}
}

func TestOnlyThisAttemptsMarkSaysItWasHandedBack(t *testing.T) {
	for _, each := range []struct {
		record *run.Object
		told   bool
	}{
		{run.Fields("handed_back", run.Float(90), "finished_at", run.Float(100)), false},
		{run.Fields("handed_back", run.Float(100), "finished_at", run.Float(100)), true},
		{run.Fields("handed_back", true, "finished_at", run.Float(100)), true},
		{run.Fields("handed_back", false), false},
		{run.Fields("handed_back", run.Float(90), "finished_at", nil, "interrupted_at", run.Float(80)), true},
	} {
		if got := handedBack(each.record); got != each.told {
			t.Errorf("%s: got %v", run.Line(each.record), got)
		}
	}
}

func TestAnEndingOverAnHourOldIsHistory(t *testing.T) {
	now := seconds()
	for _, each := range []struct {
		record *run.Object
		old    bool
	}{
		{run.Fields("finished_at", run.Float(now-2*maxAge)), true},
		{run.Fields("finished_at", run.Float(now-60)), false},
		{run.Fields("finished_at", nil, "started_at", run.Float(now-2*maxAge)), true},
		{run.Fields("finished_at", nil), false},
	} {
		if got := history(each.record); got != each.old {
			t.Errorf("%s: got %v", run.Line(each.record), got)
		}
	}
}

// seated is a home whose tmux holds seat acme up on ak's server, its harness running.
func seated(t *testing.T) string {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("AGENTKIT_SESSION", "")
	state := filepath.Join(home, ".agentkit", "state")
	bin := filepath.Join(home, "bin")
	for _, dir := range []string{state, bin} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	os.WriteFile(filepath.Join(state, "session-acme.json"), []byte(`{"orchestrator": "opus", "workers": ["opus"]}`), 0o600)
	os.WriteFile(filepath.Join(bin, "tmux"), []byte("#!/bin/sh\ncase \" $* \" in *list-sessions*) printf 'acme\\t1\\n';; *list-panes*) printf '%%1 0\\n';; esac\n"), 0o700)
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	return home
}

func TestAnEndingGoDoesNotTypeIsMarkedPendingAndSaidSo(t *testing.T) {
	home := seated(t)
	for _, ending := range []*run.Object{blocked(strings.Repeat("A complete reason sentence. ", 30)), run.Fields("state", "fail", "error", "the check failed")} {
		dir := filepath.Join(home, ".agentkit", "runs", ending.Str("state"))
		ending.Set("launched_session", "acme")
		ending.Set("finished_at", run.Float(seconds()))
		if err := os.MkdirAll(dir, 0o700); err != nil || run.Create(dir, ending) != nil {
			t.Fatal(err)
		}
		var said []string
		if Give(dir, nil, func(line string) { said = append(said, line) }) {
			t.Fatalf("%s: told", ending.Str("state"))
		}
		after, _ := run.Read(dir)
		if !after.Truthy("handback_pending") || len(said) != 1 || !strings.HasPrefix(said[0], "the acme seat is not at its prompt (") {
			t.Errorf("%s: pending %v, said %q", ending.Str("state"), after.Get("handback_pending"), said)
		}
	}
}

func TestAMarkWaitsOnNoRecoveryLock(t *testing.T) {
	dir := t.TempDir()
	snapshot := run.Fields("state", "blocked", "pid", run.Number("123"))
	if err := run.Create(dir, snapshot); err != nil {
		t.Fatal(err)
	}
	// Python's reap holds recovery.lock while it waits for delivery.lock, which a mark's caller holds
	held, err := lock.Wait(context.Background(), filepath.Join(dir, run.RecoveryLock))
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	marked := make(chan bool, 1)
	go func() { marked <- mark(dir, snapshot, "handback_pending", true) }()
	select {
	case ok := <-marked:
		if after, _ := run.Read(dir); !ok || !after.Truthy("handback_pending") {
			t.Fatal("the mark did not land")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("a mark waited on recovery.lock")
	}
}

func TestAnErrorTheTickWillRetryHasNoEndingToTell(t *testing.T) {
	home := seated(t)
	dir := filepath.Join(home, ".agentkit", "runs", "retry")
	os.MkdirAll(dir, 0o700)
	if err := run.Create(dir, run.Fields("state", "error", "launched_session", "acme", "finished_at", now(),
		"error_retry_at", run.Float(seconds()+60))); err != nil {
		t.Fatal(err)
	}
	var said []string
	if Give(dir, nil, func(line string) { said = append(said, line) }) || len(said) != 0 {
		t.Fatal("a scheduled retry was handed back", said)
	}
}
