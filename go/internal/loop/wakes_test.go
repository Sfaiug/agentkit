package loop

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"testing"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// The wake takes each red Go's woken run carries once no run it waits on holds a place in the
// line, once a pass, and leaves a PR review's, a seat's own PR's among them, and a repair's to
// Python.  A run whose lock is held, which may be a run started since the line was read, waits for
// the next wake, never on that lock.
func TestTheWakeTakesEachRedOnceNothingItWaitsOnIsInTheLine(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	line := ".merge-acme.lock"
	red := func(after *run.Object) *run.Object {
		return run.Fields("line", line, "joined", 1, "fix", run.Fields("line", "red"), "after", after)
	}
	for name, record := range map[string]*run.Object{
		"fix-1": run.Fields("waiting_on", run.Fields("line", line, "joined", 1)),
		"fix-2": run.Fields("waiting_on", red(run.Fields("fix-1", "tree"))),
		"fix-3": run.Fields("waiting_on", red(run.Fields("departed", "tree"))),
		"fix-4": run.Fields("waiting_on", red(run.NewObject()), "review_pr", "https://github.com/acme/api/pull/1"),
		"fix-5": run.Fields("waiting_on", red(run.NewObject()), "repair", true),
		"fix-6": run.Fields("waiting_on", red(run.NewObject()), "review_pr", "https://github.com/acme/api/pull/2", "own_pr", true),
		"fix-7": run.Fields("waiting_on", red(run.NewObject())),
	} {
		dir := filepath.Join(run.Runs(), name)
		// A directory at its log refuses the wake before it can spawn this test binary.
		if err := os.MkdirAll(filepath.Join(dir, "log.txt"), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := run.Create(dir, run.SetAll(record, "state", "waiting")); err != nil {
			t.Fatal(err)
		}
	}
	held, err := lock.Try(filepath.Join(run.Runs(), "fix-7", run.RecoveryLock))
	if err != nil {
		t.Fatal(err)
	}
	woken := map[string]bool{}
	tried := func() []string {
		var said bytes.Buffer
		wakeReds(line, woken, &said)
		var names []string
		for _, found := range regexp.MustCompile(`could not resume (\S+):`).FindAllStringSubmatch(said.String(), -1) {
			names = append(names, found[1])
		}
		slices.Sort(names)
		return names
	}
	if got := tried(); !slices.Equal(got, []string{"fix-3"}) {
		t.Fatalf("woke %v, want only the red waiting on no run in the line", got)
	}
	held.Close()
	if got := tried(); !slices.Equal(got, []string{"fix-7"}) {
		t.Fatalf("woke %v once fix-7's lock was free, want fix-7 alone: none again in the same pass", got)
	}
	if err := run.Change(filepath.Join(run.Runs(), "fix-1"), func(record *run.Object) error {
		run.SetAll(record, "state", "pass", "merged", true)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if got := tried(); !slices.Equal(got, []string{"fix-2"}) {
		t.Fatalf("woke %v once the run ahead left, want fix-2", got)
	}
}
