package agent

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// A held table answers for the panes it has seen, and a pane newer than it, running an agent, is
// judged by a table read again.
func TestTheHeldTableIsReadAgainForAPaneItHasNotSeen(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake tmux and ps are shell scripts")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	t.Setenv("PATH", home+string(os.PathListSeparator)+os.Getenv("PATH"))
	read, held := environ, reading.at
	t.Cleanup(func() { environ, reading.at = read, held })
	environ = func(int) ([]byte, error) { return nil, os.ErrPermission }
	reading.at = time.Time{}
	write := func(name, data string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(home, name), []byte(data), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	write("tmux", "#!/bin/sh\ncat \"$HOME/panes\"\n")
	write("ps", "#!/bin/sh\necho >>\"$HOME/ps.log\"\ncat \"$HOME/table\"\n")
	write("panes", "notes\t100\t0\n")
	write("table", "100 1 sleep 3600\n")
	readings := func() int {
		log, _ := os.ReadFile(filepath.Join(home, "ps.log"))
		return strings.Count(string(log), "\n")
	}
	if !Agentless("acme", []string{"notes"}) || !Agentless("acme", []string{"notes"}) || readings() != 1 {
		t.Fatalf("a pane running sleep, asked twice: %d readings, want 1", readings())
	}
	write("panes", "notes\t100\t0\nfix-api\t200\t0\n")
	write("table", "100 1 sleep 3600\n200 1 claude\n")
	if Agentless("acme", []string{"fix-api"}) || readings() != 2 {
		t.Fatalf("a new pane running claude was read as agentless, or read from %d readings", readings())
	}
}
