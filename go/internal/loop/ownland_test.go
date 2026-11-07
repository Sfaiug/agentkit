//go:build linux

package loop

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A seat's own PR waiting in its line on a red, a required check or a head moved past its review,
// goes back to its writer by Python's fail_pr_landing: Go's resume and its wake hand it over before
// anything is written, the record left byte for byte.  Its green, beside a task run's red, and its
// suite's red Go carries.
func TestAnOwnPRsRedLandingIsLeftToPython(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	create := func(name, line string, wait *run.Object, own bool) {
		dir := filepath.Join(run.Runs(), name)
		// A directory at its log refuses a wake before it can spawn this test binary.
		if err := os.MkdirAll(filepath.Join(dir, "log.txt"), 0o777); err != nil {
			t.Fatal(err)
		}
		record := run.Fields("state", "waiting", "scope", "none", "repo", home, "worktree", home, "branch", "contrib",
			"base", "origin/main", "base_sha", "abc1234", "waiting_on", run.SetAll(wait, "line", line, "joined", 1))
		if own {
			run.SetAll(record, "own_pr", true, "own_orchestrator", "opus", "review_pr", "https://github.com/acme/api/pull/1")
		}
		if err := run.Create(dir, record); err != nil {
			t.Fatal(err)
		}
	}
	reds := map[string]*run.Object{
		"checks": run.Fields("land", "tree", "fix", run.Fields("line", "required checks failed: ci", "log", "pr-checks.log")),
		"moved":  run.Fields("fix", run.Fields("line", "its PR's head moved to 0123abcd", "log", "lander.log", "moved", true)),
	}
	for name, wait := range reds {
		line := ".merge-" + name + ".lock"
		create(name, line, wait, true)
		path := filepath.Join(run.Runs(), name, "run.json")
		before, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		record, _ := run.Read(filepath.Dir(path))
		var said bytes.Buffer
		wakeReds(line, map[string]bool{}, &said)
		switch {
		case Woken(record):
			t.Errorf("%s: Go's resume took an own PR's red", name)
		case !LineToPython(line):
			t.Errorf("%s: Go's lander kept the pass whose wake takes an own PR's red", name)
		case said.Len() > 0:
			t.Errorf("%s: Go's wake took an own PR's red: %s", name, said.String())
		case landingFixHandoff(record) == "":
			t.Errorf("%s: Go's landing fix took an own PR's red", name)
		}
		if after, err := os.ReadFile(path); err != nil || !bytes.Equal(after, before) {
			t.Errorf("%s: the record was written: %v\n%s", name, err, after)
		}
	}
	create("green", ".merge-green.lock", run.Fields("land", "tree"), true)
	create("task", ".merge-green.lock", run.Fields("fix", run.Fields("line", "red", "log", "lander.log")), false)
	if record, _ := run.Read(filepath.Join(run.Runs(), "green")); !Woken(record) || LineToPython(".merge-green.lock") {
		t.Fatal("an own PR's green, beside a task run's red, was left to Python")
	}
	create("suite", ".merge-suite.lock", run.Fields("fix", run.Fields("line", "FAILED test_contrib", "log", "lander.log",
		"command", "pytest", "piece", "")), true)
	if record, _ := run.Read(filepath.Join(run.Runs(), "suite")); !Woken(record) || LineToPython(".merge-suite.lock") || landingFixHandoff(record) != "" {
		t.Fatal("an own PR's suite red was left to Python")
	}
}

// A PR moved or closed under its delivery waits on that red, as Python's merge_own_pr hands it to
// fail_pr_landing: the run Go woke never ends in error over it.
func TestAPullMovedUnderItsDeliveryWaitsOnItsRed(t *testing.T) {
	l, p, answers := pullRig(t, "open")
	fakeGH(t, answers)
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "head_sha", "0000000000000000000000000000000000000000", "state", "waiting",
			"waiting_on", run.Fields("line", ".merge-acme.lock", "joined", 1, "land", "tree"))
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := (&ownPull{p}).deliverPull(l, "origin/main"); err != nil {
		t.Fatal(err)
	}
	record := recorded(t, l)
	if fix := record.Dict("waiting_on").Dict("fix"); fix == nil || !fix.Truthy("moved") || !record.Truthy("review_stale") {
		t.Fatalf("the moved PR does not wait on its red: %v", record.Get("waiting_on"))
	}
}
