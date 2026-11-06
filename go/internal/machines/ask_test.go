//go:build unix

package machines

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A machine whose ssh is gone at once, leaving a child to answer after the timeout, is a miss: the
// deadline holds for all the ask started, not its first process.
func TestAnAnswerAfterTheTimeoutIsAMiss(t *testing.T) {
	home, bin := t.TempDir(), t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	answer := "system Linux\nprocessor x86_64\ncores 4\nmemory_mb 8192\nfree_mb 4096\nload 0.25\n" +
		"disk_free_mb 102400\nbattery 0\npower 1\n"
	for path, text := range map[string]string{
		filepath.Join(home, ".agentkit", "config.toml"): "[machines.acme]\n",
		filepath.Join(bin, "ssh"):                       "#!/bin/sh\n(sleep 12; printf '" + answer + "') &\n",
	} {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Mkdir(filepath.Join(home, ".agentkit", "state"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := Check(); err != nil {
		t.Fatal(err)
	}
	record, err := run.ReadJSON(path())
	if err != nil {
		t.Fatal(err)
	}
	if acme := record.Dict("acme"); acme == nil || acme.Get("said") != nil {
		t.Fatalf("acme answered after the timeout: %s", run.Line(record))
	}
}
