//go:build linux

package loop

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestAMergeWritingIntoItsLogDoesNotReplayIt(t *testing.T) {
	l := rig(t, time.Minute)
	log, err := os.OpenFile(filepath.Join(l.dir, "log.txt"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	stdout := os.Stdout
	os.Stdout = log
	t.Cleanup(func() { os.Stdout = stdout; log.Close() })
	var out bytes.Buffer
	// No task was saved: the delivery ends in error after writing its own messages.
	code, why, err := Merge(l.dir, &out, io.Discard)
	if code != 2 || why != "" || err != nil {
		t.Fatalf("merge: %d, %q, %v", code, why, err)
	}
	if out.Len() != 0 {
		t.Fatalf("replayed its log: %s", out.String())
	}
}
