package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

func TestMenuStopHandoffAndDetachedCleanup(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	t.Setenv("HOME", t.TempDir())
	program := filepath.Join(t.TempDir(), "ak")
	build := exec.Command("go", "build", "-o", program, "./cmd/ak")
	build.Dir = "../.."
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	call := exec.Command("python3", "-B", "-c", `
import fcntl, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

def popup(home, size=(100, 30)):
    return Terminal(home, "attach", "--overlay", size=size,
                    env={"AGENTKIT_SESSION": "acme"}, program=sys.argv[1])

with Home() as home:
    Seat(home, "acme", screen="claude-working-pane.txt")
    Seat(home, "beta")
    menu = popup(home)
    menu.wait("x stop")
    menu.keys("j")
    menu.wait("› 2  beta")
    menu.keys("x")
    menu.wait("Stop acme and everything it runs?")
    state = home.path / ".agentkit/state"
    with (state / "watch.lock").open("a") as gate:
        fcntl.flock(gate, fcntl.LOCK_EX)
        menu.keys("Down", "Enter")
        assert menu.exit_code() == 0
        assert home.tmux("has-session", "-t", "=acme").code == 0
        mark = state / "seat-acme.json"
        assert "stopped_at" not in (json.loads(mark.read_text()) if mark.exists() else {})
    deadline = time.monotonic() + 30
    while home.tmux("has-session", "-t", "=acme").code == 0:
        assert time.monotonic() < deadline, "detached stop never finished"
        time.sleep(0.05)
    assert json.loads((state / "seat-acme.json").read_text())["closed_by_owner"] is True
    assert home.tmux("has-session", "-t", "=beta").code == 0
    returned = popup(home)
    returned.wait("p past")
    returned.keys("Escape")
    assert returned.exit_code() == 0

with Home() as home:
    Seat(home, "acme", screen="claude-working-pane.txt")
    menu = popup(home)
    menu.wait("x stop")
    home.write(".agentkit/state/browser-tabs.json", {"T1": {"opener": {"session": "acme"}}})
    state = home.path / ".agentkit/state"
    menu.keys("x")
    assert menu.exit_code() == 3, "an unsupported stop must hand over before asking"
    mark = state / "seat-acme.json"
    assert "stopped_at" not in (json.loads(mark.read_text()) if mark.exists() else {})
    assert home.tmux("has-session", "-t", "=acme").code == 0

for size in ((40, 12), (24, 16), (80, 10), (80, 8), None):
    with Home() as home:
        Seat(home, "acme", screen="claude-working-pane.txt")
        Seat(home, "beta")
        menu = popup(home, size or (100, 30))
        menu.wait("x stop")
        menu.keys("x")
        if size is None:
            menu.wait("Stop acme and everything it runs?")
            menu.resize(80, 8)
        assert menu.exit_code() == 3, "a card that cannot fit must hand over"
        for name in ("acme", "beta"):
            mark = home.path / f".agentkit/state/seat-{name}.json"
            assert "stopped_at" not in (json.loads(mark.read_text()) if mark.exists() else {})
            assert home.tmux("has-session", "-t", f"={name}").code == 0
`, program)
	call.Dir = "../../.."
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("popup stop: %v\n%s", err, out)
	}
}
