package loop

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/history"
	"agentkit/internal/pick"
	"agentkit/internal/run"
)

// lineupHome is a home with no history whose stored lineup has a row its one model runs, and a
// run of that model's about to be launched there, its loop and its record.
func lineupHome(t *testing.T) (*loop, *run.Object, string) {
	t.Helper()
	home := t.TempDir()
	for name, value := range map[string]string{"HOME": home, "USERPROFILE": home, "XDG_CACHE_HOME": t.TempDir(),
		"AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_NOTIFY_SINK": ""} {
		t.Setenv(name, value)
	}
	write := func(path, text string, mode os.FileMode) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), mode); err != nil {
			t.Fatal(err)
		}
	}
	ak := filepath.Join(home, ".agentkit")
	write(filepath.Join(ak, "state", "matrix.json"), `{"matrix": {"lineup": [{"release": "acme-5", "maker": "Acme", "effort": "high",
		"values": {"aa.intelligenceIndex": 50, "arena.agent": 0.6, "aa.frontierCode20": 0.6}, "yours": [{"harness": "echo", "model": "acme-5"}]}]}}`, 0o600)
	write(filepath.Join(ak, "config.toml"), "companies = ['Acme']\n[defaults]\norchestrator = 'five'\nworkers = ['five']\n"+
		"[providers.p]\nmode = 'subscription'\n[models.five]\nharness = 'echo'\nmodel = 'acme-5'\neffort = 'high'\nprovider = 'p'\n", 0o600)
	adapters := filepath.Join(home, "adapters")
	write(filepath.Join(adapters, "echo.sh"), "#!/bin/sh\ncase \"$1\" in auth) echo yes;; usage) echo '{\"meters\": []}';; esac\n", 0o700)
	write(filepath.Join(adapters, "echo.toml"), "version = 1\n", 0o600)
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	dir := filepath.Join(ak, "runs", "20261113-1200-fix-api")
	record := run.Fields("run_id", filepath.Base(dir), "state", "running", "workers", []any{"five"}, "reviewers", []any{"five"})
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := run.Create(dir, record); err != nil {
		t.Fatal(err)
	}
	return &loop{ctx: context.Background(), dir: dir, id: filepath.Base(dir), workers: []string{"five"}, reviewers: []string{"five"}}, record, ak
}

// A run Go launched, having decided before writing anything that Go ranks it, picks as decided
// once its own history row is written: a task's executor and reviewer, a pull request's reviewer.
func TestARunGoLaunchedPicksPastItsOwnHistoryRow(t *testing.T) {
	for _, kind := range []string{"task", "pull request"} {
		t.Run(kind, func(t *testing.T) {
			l, record, _ := lineupHome(t)
			if _, ok := pick.Within(l.workers, l.reviewers); !ok {
				t.Fatal("the launch hands the pick over")
			}
			history.Start(record, func(line string) { t.Log(line) })
			first := l.pick
			if kind == "pull request" {
				first = func() error { return l.pickReviewer("its pull request") }
			}
			err := first()
			if err != nil || l.reviewer != "five" || kind == "task" && l.executor != "five" {
				t.Fatalf("picked %q and %q: %v", l.executor, l.reviewer, err)
			}
		})
	}
}

// Its own row aside, a run's history counts as at its launch: where history.db holds another run,
// the run's pick hands over as the launch would have, before the meters are read.
func TestARunGoLaunchedHandsOverPastAnotherHistoryRow(t *testing.T) {
	l, record, ak := lineupHome(t)
	history.Start(run.Fields("run_id", "20261112-1200-fix-old-api", "state", "running"), func(line string) { t.Log(line) })
	history.Start(record, func(line string) { t.Log(line) })
	if err := l.pick(); err == nil {
		t.Fatalf("picked %q and %q past another run's row", l.executor, l.reviewer)
	}
	if _, err := os.Stat(filepath.Join(ak, "state", "usage.json")); !os.IsNotExist(err) {
		t.Fatalf("usage.json was written before handing over: %v", err)
	}
}

// A resume launches the run anew: where history.db holds a run, its own, the rank is Python's,
// handed over before the meters are read, usage.json unwritten.
func TestAResumeHandsOverTheRankBeforeReadingTheMeters(t *testing.T) {
	_, record, ak := lineupHome(t)
	history.Start(record, func(line string) { t.Log(line) })
	if _, _, ok := picking(record, false); ok {
		t.Fatal("the resume's pick is Go's")
	}
	if _, err := os.Stat(filepath.Join(ak, "state", "usage.json")); !os.IsNotExist(err) {
		t.Fatalf("usage.json was written before handing over: %v", err)
	}
}
