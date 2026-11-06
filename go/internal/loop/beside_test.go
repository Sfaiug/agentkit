//go:build !windows

package loop

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A review that ends while the base proof's git is still running stops that git before joining:
// the fake one never ends on its own, so a drop that waited on it would never return.
func TestADroppedProofStopsItsGit(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_SESSION", "")
	started := filepath.Join(home, "started")
	fake := "#!/bin/sh\ntouch '" + started + "'\nexec sleep 100000\n"
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
	for _, err := os.Stat(started); err != nil; _, err = os.Stat(started) {
		time.Sleep(10 * time.Millisecond)
	}
	proof.drop()
	if _, err := proof.join(); !errors.Is(err, context.Canceled) {
		t.Fatalf("the proof ended on its own, not by its drop: %v", err)
	}
}
