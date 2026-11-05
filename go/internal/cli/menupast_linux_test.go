package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

func TestMenuPastAdmissionAndOwnerRemoval(t *testing.T) {
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
import json, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

for remove_directory in (False, True):
    with Home() as home:
        Seat(home, "fix-api")
        beta = Seat(home, "beta", model="fable")
        menu = Terminal(home, program=sys.argv[1])
        menu.wait("beta")
        if remove_directory:
            shutil.rmtree(beta.cwd)
        stopped = home.run(sys.argv[1], "orch", "stop", "beta")
        assert stopped.code == 0, stopped
        if remove_directory:
            assert menu.exit_code(bound=25) == 3, menu.screen()
        else:
            menu.wait("p past")
            menu.keys("Escape")
            assert menu.exit_code() == 0

mark = {"stopped_at": time.time() - 9000, "closed_by_owner": True}
for file, data in (
    ("state/notify-beta.json", {"kind": "needs", "text": "Which branch?", "seen": True}),
    ("runs/api/run.json", {"state": "pass", "launched_session": "beta", "worktree": "/wt/api"}),
    ("state/browser-tabs.json", {"T1": {"opener": {"session": "beta"}}}),
):
    with Home() as home:
        Seat(home, "fix-api")
        Seat(home, "beta", model="fable", alive=False)
        home.write(".agentkit/state/seat-beta.json", mark)
        home.write(".agentkit/" + file, data)
        menu = Terminal(home, program=sys.argv[1])
        assert menu.exit_code() == 3, (file, menu.screen())
        assert "esc leave" not in menu.screen(), menu.screen()
        assert json.loads((home.path / ".agentkit/state/seat-beta.json").read_text()) == mark

with Home() as home:
    Seat(home, "fix-api")
    Seat(home, "beta", model="fable", alive=False)
    home.write(".agentkit/state/seat-beta.json", mark)
    home.write(".agentkit/state/plan-beta.md", "- [x] " + "Checked all the changes " * 200 + ".\n")
    menu = Terminal(home, "attach", "--overlay", size=(80, 12),
                    env={"AGENTKIT_SESSION": "fix-api"}, program=sys.argv[1])
    menu.wait("p past")
    menu.keys("p")
    menu.wait(lambda text: text.startswith("agentkit · past sessions") and "esc back" in text)
    menu.resize(40, 16)
    menu.wait(lambda text: text.startswith("agentkit · past sessions") and "esc back" in text)
    menu.resize(100, 30)
    menu.wait("x remove")
    menu.keys("x")
    menu.wait("Remove beta from past sessions?")
    menu.keys("Escape")
    menu.wait("x remove")
    assert (home.path / ".agentkit/state/session-beta.json").exists()
    menu.keys("x")
    menu.wait("Remove beta from past sessions?")
    menu.keys("Down", "Enter")
    menu.wait(lambda text: "esc leave" in text and "p past" not in text)
    assert not (home.path / ".agentkit/state/session-beta.json").exists()
    after = json.loads((home.path / ".agentkit/state/seat-beta.json").read_text())
    assert {key: after.get(key) for key in mark} == mark
    assert home.tmux("has-session", "-t", "=fix-api").code == 0
    menu.keys("Escape")
    assert menu.exit_code() == 0
`, program)
	call.Dir = "../../.."
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("past admission and removal: %v\n%s", err, out)
	}
}
