//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// A delivery's end wakes the line's next delivery beside it, not below it: the next run's resume
// carries none of the ending run's marker, which that run's own sweep stops as it ends.
func TestADeliveryHandsOnItsTurnOutsideItsOwnSweep(t *testing.T) {
	l, r := repoRig(t)
	t.Setenv(host.Marker, l.dir) // as its driver carries it
	shell(t, r.repo, "git remote add origin "+r.repo)
	shell(t, r.wt, "echo own > own.txt; git add -A; git commit -qm own")
	head, tree, err := r.identity()
	if err != nil {
		t.Fatal(err)
	}
	turn, err := r.turn("origin/main")
	if err != nil {
		t.Fatal(err)
	}
	// a pass's place held: the delivery's own handing on is the only wake
	lander, err := lock.Try(beside(turn, ".lander.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer lander.Close()
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "state", "running", "pid", os.Getpid(), "process_identity", Identity(os.Getpid()),
			"scope", "none", "base", "origin/main", "target", "main", "base_sha", r.baseSHA,
			"review", run.Fields("verdict", "PASS", "head_sha", head, "tree_sha", tree),
			"waiting_on", run.Fields("line", filepath.Base(turn), "joined", 1, "land", tree))
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	next := filepath.Join(run.Runs(), "fix-next")
	if err := os.MkdirAll(next, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := run.Create(next, run.Fields("state", "waiting",
		"waiting_on", run.Fields("line", filepath.Base(turn), "joined", 2, "land", "next-tree"))); err != nil {
		t.Fatal(err)
	}
	ended := filepath.Join(os.Getenv("HOME"), "ended")
	t.Setenv("AK_TEST_WAKE_ENDED", ended)
	record, _ := run.Read(l.dir)
	if err := r.landFromLine(l, "origin/main", record, func() error {
		return l.save(func(record *run.Object) { record.Set("merged", true) })
	}); err != nil {
		t.Fatal(err)
	}
	wakesUnderWay.Wait()
	marked, err := os.ReadFile(ended)
	if err != nil {
		t.Fatal("the delivery's end did not wake the next delivery")
	}
	if len(marked) != 0 {
		t.Fatalf("the next delivery's resume is marked for %s's sweep", marked)
	}
}
