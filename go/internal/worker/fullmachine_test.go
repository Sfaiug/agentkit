//go:build linux

package worker

import (
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/box"
)

// TestMain is the box's first process where a turn run here starts this test program as one.
func TestMain(m *testing.M) {
	if code, first := box.First(); first {
		os.Exit(code)
	}
	os.Exit(m.Run())
}

// A turn a full machine refused runs here under a watch of its own, as Python's launch watches it
// afresh: neither the time the machine took to refuse it nor that it took to let it go is any of
// its silence.  Each try here and there is within the silence limit; all of them are not.
func TestAFullMachinesTurnRunsHereWithAWholeSilenceLimit(t *testing.T) {
	if err := box.Check(); err != nil {
		t.Skip(err)
	}
	root, repo, put, _ := aMachineTakesTurns(t, `sleep 1.5; echo here >"$6/session_id"`)
	put(filepath.Join(root, "bin", "ssh"), "#!/bin/sh\neval \"set -- $8\"\ncase \"$5\" in\n"+
		"probe) printf 'cpus 2\\nload 0\\nroom_mb 65536\\nturns 1\\n' ;;\nprepare) cat >/dev/null ;;\n"+
		"turn) sleep 1.5; exit 252 ;;\nfinish) sleep 2 ;;\nesac\n")
	code, session, err := Turn("glint", "reviewer", "review it", repo, filepath.Join(root, "out"), "", Given{Silence: 3 * time.Second}, io.Discard)
	if code != 0 || session != "here" || err != nil {
		t.Fatalf("the turn the full machine refused: exit %d, conversation %q, %v", code, session, err)
	}
}
