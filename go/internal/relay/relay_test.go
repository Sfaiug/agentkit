//go:build unix

package relay

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// relayed runs script under Run with typed on its stdin, then its end, and shown reading its
// stdout; closed shuts that reader first, so every write to stdout fails.  It answers Run's
// answer and what reached stdout.
func relayed(t *testing.T, script, typed string, closed bool, name func(string) error) (int, error, string) {
	t.Helper()
	stdin, keys, _ := os.Pipe()
	shown, stdout, _ := os.Pipe()
	saved := [2]*os.File{os.Stdin, os.Stdout}
	os.Stdin, os.Stdout = stdin, stdout
	t.Cleanup(func() { os.Stdin, os.Stdout = saved[0], saved[1] })
	go func() {
		keys.WriteString(typed)
		keys.Close()
	}()
	if closed {
		shown.Close()
	}
	out := make(chan string)
	go func() {
		all, _ := io.ReadAll(shown)
		out <- string(all)
	}()
	code, err := Run(exec.Command("sh", "-c", script), name)
	stdout.Close()
	if closed {
		return code, err, ""
	}
	return code, err, <-out
}

func named(string) error { return nil }

func TestTheProgramsOutputInputAndExitAreTheRelays(t *testing.T) {
	// cat ends only at the end of its input: the ^D the relay passes
	code, err, shown := relayed(t, "cat; echo cat ended; exit 7", "fix the api\n", false, named)
	if code != 7 || err != nil || strings.Count(shown, "fix the api") != 2 || !strings.Contains(shown, "cat ended") {
		t.Fatalf("answered %d %v, showed %q", code, err, shown)
	}
	if code, err, _ := relayed(t, "kill -KILL $$", "", false, named); code != 137 || err != nil {
		t.Fatalf("a program a KILL ended answered %d %v", code, err)
	}
}

func TestAProgramWhoseTerminalCannotBeNamedNeverStarts(t *testing.T) {
	started, path := filepath.Join(t.TempDir(), "started"), ""
	code, err, _ := relayed(t, "touch "+started, "", false, func(tty string) error {
		path = tty
		return errors.New("no pane")
	})
	if _, gone := os.Stat(started); code != 127 || err == nil || !os.IsNotExist(gone) || !strings.HasPrefix(path, "/dev/") {
		t.Fatalf("answered %d %v after naming %q", code, err, path)
	}
}

func TestAProcessHoldingTheTerminalPastTheProgramsExitHoldsNoRelay(t *testing.T) {
	held := filepath.Join(t.TempDir(), "held")
	os.WriteFile(held, nil, 0o600)
	defer os.Remove(held) // the holder's end, however the test goes
	done := make(chan string)
	go func() {
		// deaf from its start to the HUP its terminal's leader leaves it as it exits
		holder := "trap '' HUP; (while [ -e " + held + " ]; do sleep 0.05; done) & "
		code, _, shown := relayed(t, holder+"echo bye; exit 3", "", false, named)
		done <- fmt.Sprintf("%s %d", strings.TrimSpace(shown), code)
	}()
	select {
	case got := <-done:
		if got != "bye 3" {
			t.Fatalf("showed and answered %q", got)
		}
	case <-time.After(time.Minute):
		t.Fatal("the relay waited for its terminal's end")
	}
}

func TestARelayThatFailsHangsUpItsProgramAndKillsOneThatStays(t *testing.T) {
	heard := filepath.Join(t.TempDir(), "heard")
	for _, trap := range []string{"echo HUP >" + heard + "; exit 0", ""} {
		code, err, _ := relayed(t, "trap '"+trap+"' HUP; while :; do echo busy; sleep 0.01; done", "", true, named)
		if code != 1 || err == nil {
			t.Fatalf("trap %q: answered %d %v", trap, code, err)
		}
	}
	if said, _ := os.ReadFile(heard); string(said) != "HUP\n" {
		t.Fatalf("the program heard %q", said)
	}
}
