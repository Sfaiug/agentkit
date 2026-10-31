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

// relayed runs script under Run with typed on its stdin, then its end, and answers Run's answer
// and what reached its stdout.
func relayed(t *testing.T, script, typed string, name func(string) error) (int, error, string) {
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
	out := make(chan string)
	go func() {
		all, _ := io.ReadAll(shown)
		out <- string(all)
	}()
	code, err := Run(exec.Command("sh", "-c", script), name)
	stdout.Close()
	return code, err, <-out
}

func named(string) error { return nil }

func TestTheProgramsOutputInputAndExitAreTheRelays(t *testing.T) {
	// cat ends only at the end of its input: the ^D the relay passes
	code, err, shown := relayed(t, "cat; echo cat ended; exit 7", "fix the api\n", named)
	if code != 7 || err != nil || strings.Count(shown, "fix the api") != 2 || !strings.Contains(shown, "cat ended") {
		t.Fatalf("answered %d %v, showed %q", code, err, shown)
	}
	if code, err, _ := relayed(t, "kill -KILL $$", "", named); code != 137 || err != nil {
		t.Fatalf("a program a KILL ended answered %d %v", code, err)
	}
}

func TestAProgramWhoseTerminalCannotBeNamedNeverStarts(t *testing.T) {
	started, path := filepath.Join(t.TempDir(), "started"), ""
	code, err, _ := relayed(t, "touch "+started, "", func(tty string) error {
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
		code, _, shown := relayed(t, holder+"echo bye; exit 3", "", named)
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

// The relay runs in a copy of this test whose own stdout is a pipe nobody reads, so every write
// to it fails, as on a seat's terminal that is gone.
func TestARelayThatFailsHangsUpItsProgramAndKillsOneThatStays(t *testing.T) {
	if script := os.Getenv("AK_RELAY_SCRIPT"); script != "" {
		code, err := Run(exec.Command("sh", "-c", script), named)
		fmt.Fprint(os.Stderr, err)
		os.Exit(code)
	}
	folder := t.TempDir()
	heard := filepath.Join(folder, "heard")
	for _, trap := range []string{"echo HUP >" + heard + "; exit 0", ""} {
		// busy until the test's folder goes, whatever the relay does
		script := "trap '" + trap + "' HUP; while [ -d " + folder + " ]; do echo busy; sleep 0.01; done"
		wrapper, said := exec.Command(os.Args[0], "-test.run=^"+t.Name()+"$"), &strings.Builder{}
		wrapper.Env, wrapper.Stderr = append(os.Environ(), "AK_RELAY_SCRIPT="+script), said
		shown, stdout, _ := os.Pipe()
		shown.Close()
		wrapper.Stdout = stdout
		wrapper.Run()
		stdout.Close()
		if code := wrapper.ProcessState.ExitCode(); code != 1 || said.Len() == 0 {
			t.Fatalf("trap %q: answered %d, saying %q", trap, code, said)
		}
	}
	if said, _ := os.ReadFile(heard); string(said) != "HUP\n" {
		t.Fatalf("the program heard %q", said)
	}
}
