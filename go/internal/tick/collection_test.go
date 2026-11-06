//go:build unix

package tick

import (
	"io"
	"net"
	"os"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"agentkit/internal/gc"
)

// This test program started as the tick's collector ends at once, so a collection started by
// mistake never runs these tests again.
func init() {
	if len(os.Args) > 1 && os.Args[1] == gc.CollectVerb {
		os.Exit(0)
	}
}

// A due collection whose plan is Python's hands the tick over at its row where a user manager
// runs, before any collector of Go's starts: a detached collector's handover would reach nobody.
// Elsewhere the tick goes on.
func TestACollectionPythonPlansHandsTheTickOverUnderAUserManager(t *testing.T) {
	ak, _ := idleHome(t, answers)
	if err := os.Remove(filepath.Join(ak, "state", "gc.json")); err != nil {
		t.Fatal(err)
	}
	// a seat record Go does not read as Python does, whose cursor is Python's to take out
	put(t, filepath.Join(ak, "state", "session-acme.json"), "{\"name\": \"\xff\"}")
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	row := slices.IndexFunc(table(tick), func(row pass) bool { return row.name == "collection" })
	if row < 0 {
		t.Fatal("no collection row")
	}
	collection := table(tick)[row : row+1]
	if !tick.through(collection) {
		t.Fatal("the tick went to Python with no user manager")
	}
	// a user manager as host.UserManager finds one: systemd-run, and its control socket listening
	bin := t.TempDir()
	put(t, filepath.Join(bin, "systemd-run"), "#!/bin/sh\nexit 1\n")
	if err := os.Chmod(filepath.Join(bin, "systemd-run"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	if err := os.Mkdir(filepath.Join(os.Getenv("XDG_RUNTIME_DIR"), "systemd"), 0o700); err != nil {
		t.Fatal(err)
	}
	manager, err := net.Listen("unix", filepath.Join(os.Getenv("XDG_RUNTIME_DIR"), "systemd", "private"))
	if err != nil {
		t.Fatal(err)
	}
	defer manager.Close()
	if tick.through(collection) {
		t.Fatal("the tick carried a collection Python plans under a user manager")
	}
}
