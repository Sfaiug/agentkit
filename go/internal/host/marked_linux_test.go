//go:build linux

package host

import (
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// A helper told to end starts a child and exits: that child carries the marker too, and goes with it.
func TestASweepEndsWhatAProcessStartsOnItsWayOut(t *testing.T) {
	defer func(grace time.Duration) { endGrace = grace }(endGrace)
	endGrace = 300 * time.Millisecond
	marker := t.TempDir()
	child, ready := filepath.Join(marker, "child"), filepath.Join(marker, "ready")
	cmd := exec.Command("sh", "-c", `trap 'sleep 60 & echo $! >"$1"; exit 0' TERM; : >"$2"; while :; do sleep 0.02; done`, "sh", child, ready)
	cmd.Env = append(os.Environ(), Marker+"="+marker)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	go cmd.Wait()
	for late := time.Now().Add(10 * time.Second); ; time.Sleep(10 * time.Millisecond) {
		if _, err := os.Stat(ready); err == nil {
			break
		}
		if time.Now().After(late) {
			t.Fatal("the helper did not start")
		}
	}
	EndMarked(marker, io.Discard)
	said, err := os.ReadFile(child)
	if err != nil {
		t.Fatal(err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(said)))
	if err != nil {
		t.Fatal(err)
	}
	if stat, ok := ReadStat(pid); ok && !stat.Exited() {
		t.Fatalf("process %d outlived the sweep", pid)
	}
}
