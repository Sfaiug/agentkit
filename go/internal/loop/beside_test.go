//go:build linux

package loop

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// A review that ends while the base proof's git is still running stops that git and what it
// started, as a filter is, before joining: neither ends on its own, so a drop that waited on
// either would never return or would leave it running.
func TestADroppedProofStopsItsGitAndWhatItStarted(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_SESSION", "")
	child := filepath.Join(home, "child")
	// the child keeps the git's output open, as a git's filter does
	fake := "#!/bin/sh\nsleep 100000 &\necho $! > '" + child + ".new' && mv '" + child + ".new' '" + child + "'\nexec sleep 100000\n"
	if err := os.WriteFile(filepath.Join(home, "git"), []byte(fake), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", home+string(os.PathListSeparator)+os.Getenv("PATH"))
	if err := run.Create(home, run.Fields("state", "running", "base_proof", "owed")); err != nil {
		t.Fatal(err)
	}
	l := &loop{ctx: context.Background(), dir: home, every: []string{"true"}}
	proof, err := (&repoPlace{wt: home, baseSHA: strings.Repeat("0", 40)}).baseProof(l, true)
	if err != nil || proof == nil {
		t.Fatalf("no proof started: %v", err)
	}
	said, err := os.ReadFile(child)
	for ; err != nil; said, err = os.ReadFile(child) {
		time.Sleep(10 * time.Millisecond)
	}
	pid, _ := strconv.Atoi(strings.TrimSpace(string(said)))
	t.Cleanup(func() { syscall.Kill(pid, syscall.SIGKILL) })
	proof.drop()
	if _, err := proof.join(); !errors.Is(err, context.Canceled) {
		t.Fatalf("the proof ended on its own, not by its drop: %v", err)
	}
	if stat, ok := host.ReadStat(pid); ok && !stat.Exited() {
		t.Fatalf("the drop returned with the git's child %d still running", pid)
	}
}
