//go:build !windows

package cli

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A stop from inside the seat ends the very pane it runs in; the hangup must not end the stop,
// whose runs stop only once the seat has gone.
func TestOrchStopOutlivesItsOwnPane(t *testing.T) {
	if ended := os.Getenv("AK_TEST_STOP_INSIDE"); ended != "" {
		code := Main([]string{"orch", "stop", "acme"}, os.Stdout, os.Stderr)
		os.WriteFile(ended, nil, 0o600) // the stop's last write
		os.Exit(code)
	}
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	home := sandbox(t)
	sockets, err := os.MkdirTemp("", "ak") // short: tmux refuses a long socket path
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(sockets) })
	t.Setenv("TMUX_TMPDIR", sockets)
	t.Setenv("AGENTKIT_TMUX_SOCKET", "stop-test")
	t.Setenv("XDG_RUNTIME_DIR", t.TempDir()) // no user manager, whose unit the stop leaves to Python
	record := filepath.Join(home, ".agentkit", "runs", "r-going", "run.json")
	write(t, record, `{"run_id": "r-going", "state": "running", "launched_session": "acme"}`)
	ready, ended := filepath.Join(home, "marked"), filepath.Join(home, "ended")
	tmux := func(args ...string) {
		t.Helper()
		if out, err := exec.Command("tmux", append([]string{"-L", "stop-test", "-f", "/dev/null"}, args...)...).CombinedOutput(); err != nil {
			t.Fatalf("tmux %v: %v: %s", args, err, out)
		}
	}
	tmux("new-session", "-d", "-s", "acme", "-e", "HOME="+home, "-e", "AGENTKIT_SESSION=acme", "-e", "AK_TEST_STOP_INSIDE="+ended, "sh", "-c",
		`while [ ! -e "$0" ]; do sleep 0.05; done; exec "$1" -test.run='^TestOrchStopOutlivesItsOwnPane$'`, ready, self)
	t.Cleanup(func() { exec.Command("tmux", "-L", "stop-test", "kill-server").Run() })
	tmux("set-option", "-t", "=acme:", "@ak_orch", "1")
	write(t, ready, "")
	// The stop's end, not its run's: it writes the seat's state after the run's, into the HOME
	// the test's end removes.
	for deadline := time.Now().Add(time.Minute); ; time.Sleep(20 * time.Millisecond) {
		if _, err := os.Stat(ended); err == nil {
			if held, _ := run.ReadJSON(record); held == nil || held.Str("state") != "stopped" {
				t.Fatal("the stop ended with its run still going")
			}
			return
		}
		if time.Now().After(deadline) {
			t.Fatal("the stop never ended: it died with its pane")
		}
	}
}
