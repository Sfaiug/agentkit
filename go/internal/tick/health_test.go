//go:build unix

package tick

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/lock"
)

// A holder of 30 minutes reads as hung though a tick ended just now; the same old file with
// nobody holding it does not.
func TestAHolderOfThirtyMinutesReadsAsHung(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	state := filepath.Join(home, ".agentkit", "state")
	if err := os.MkdirAll(state, 0o700); err != nil {
		t.Fatal(err)
	}
	now := float64(time.Now().Unix())
	record, _ := json.Marshal(map[string]any{"tick": map[string]any{"started_at": now - 2, "ended_at": now,
		"slowest": map[string]any{"pass": "acme", "seconds": 1.5}}})
	if err := os.WriteFile(filepath.Join(state, "watch.json"), record, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(lockPath(), []byte("4242\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	old := time.Now().Add(-hung - time.Minute)
	if err := os.Chtimes(lockPath(), old, old); err != nil {
		t.Fatal(err)
	}
	if line, stuck, ok := Health(); !ok || stuck || !strings.HasPrefix(line, "lock free · ended <1m ago, took 2.0 s, slowest acme 1.5 s · ") {
		t.Fatalf("free: %q stuck=%v ok=%v", line, stuck, ok)
	}
	held, err := lock.Try(lockPath())
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	if line, stuck, ok := Health(); !ok || !stuck || !strings.HasPrefix(line, "lock held by pid 4242 for 31 min · ") {
		t.Fatalf("held: %q stuck=%v ok=%v", line, stuck, ok)
	}
}
