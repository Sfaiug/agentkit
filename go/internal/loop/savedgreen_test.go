//go:build linux

package loop

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestSavedGreenWakesBeforeRebuildingOnAMovedTarget(t *testing.T) {
	l, r := repoRig(t)
	shell(t, r.repo, "git remote add origin "+r.repo)
	shell(t, r.wt, "echo own > own.txt; git add -A; git commit -qm own")
	head, tree, err := r.identity()
	if err != nil {
		t.Fatal(err)
	}
	turn := filepath.Join(run.Runs(), ".merge-acme.lock")
	if err := run.Change(l.dir, func(record *run.Object) error {
		run.SetAll(record, "state", "waiting", "base", "main", "target", "main", "base_sha", r.baseSHA,
			"review", run.Fields("verdict", "PASS", "head_sha", head, "tree_sha", tree, "done_when", true),
			"waiting_on", run.Fields("line", filepath.Base(turn), "joined", 1, "land", tree, "after", run.NewObject()))
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	shell(t, r.repo, "echo ahead > ahead.txt; git add -A; git commit -qm ahead")
	// Refuse the launch before it can spawn a child: its warning proves the saved wake was tried.
	if err := os.Mkdir(filepath.Join(l.dir, "log.txt"), 0o777); err != nil {
		t.Fatal(err)
	}
	var said bytes.Buffer
	if err := checkTurn(turn, "", &said); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(said.String(), "WARN could not resume "+filepath.Base(l.dir)+":") {
		t.Fatalf("saved green verdict was not woken after the target moved: %s", said.String())
	}
}
