//go:build linux

package loop

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestNarrowingProbeLeavesTheOriginalTreeForItsWholeCheck(t *testing.T) {
	l, repo := repoRig(t)
	head, tree, err := repo.identity()
	if err != nil {
		t.Fatal(err)
	}
	stack := &narrowingStack{l: l, checkout: &landingCheckout{path: repo.wt}, head: head, tree: tree}
	stack.dir = l.dir
	answer, err := stack.checkTests("touch probe-output", "", &checkSelection{shard: "1/1"})
	if err != nil || answer == nil || !answer.Has("land") {
		t.Fatalf("probe: %v, %v", answer, err)
	}
	if _, err := os.Stat(filepath.Join(repo.wt, "probe-output")); !os.IsNotExist(err) {
		t.Fatalf("probe output survived into the next check: %v", err)
	}
	answer, err = stack.check([]string{"test ! -e probe-output"}, "", &checkSelection{})
	if err != nil || answer == nil || !answer.Has("land") {
		t.Fatalf("whole check: %v, %v", answer, err)
	}
}

func TestDeliveryRedRetainsItsFixReceipt(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	dir := filepath.Join(run.Runs(), "fix-api")
	if err := os.MkdirAll(dir, 0o777); err != nil {
		t.Fatal(err)
	}
	wait := run.Fields("line", ".merge-acme.lock", "joined", 1, "land", "tree",
		"fix", run.Fields("line", "required checks failed"), "after", run.Fields("first", "first-tree"))
	if err := run.Create(dir, run.Fields("state", "waiting", "waiting_on", wait, "review", run.Fields("verdict", "PASS"))); err != nil {
		t.Fatal(err)
	}
	saved, _ := run.Read(dir)
	if err := narrowLine("", "", "", "", "", []member{{dir, saved}}, io.Discard); err != nil {
		t.Fatal(err)
	}
	current, _ := run.Read(dir)
	if !run.Equal(current.Dict("waiting_on"), wait) {
		t.Fatalf("a delivery red was replaced by a new stack check: %s", run.Encode(current))
	}
}
