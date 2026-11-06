package seat

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A run whose directory is a link is walked through it, as os.walk enters its starting directory.
func TestALinkedRunIsWalkedThroughItsLink(t *testing.T) {
	home := sandbox(t)
	file := runRecord(t, home, "quiet", map[string]any{"state": "running", "started_at": seconds(moment.Add(-4 * time.Hour))})
	if err := os.Chtimes(file, moment.Add(-3*time.Hour), moment.Add(-3*time.Hour)); err != nil {
		t.Fatal(err)
	}
	dir, target := filepath.Dir(file), filepath.Join(home, "kept-run")
	left := filepath.Join(target, "sandbox", "left.txt")
	if err := os.Rename(dir, target); err != nil {
		t.Fatal(err)
	}
	write(t, left, "left\n")
	if err := os.Chtimes(left, moment.Add(-2*time.Hour), moment.Add(-2*time.Hour)); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, dir); err != nil {
		t.Skip("no symlinks here:", err)
	}
	record, err := run.Read(dir)
	if err != nil {
		t.Fatal(err)
	}
	if got := silence(dir, record, moment); got != 2*3600 {
		t.Fatalf("silent %vs, want the sandbox's 7200s", got)
	}
}
