package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

func TestConfigRestartHandoffsLeaveRecordAndConfigBytesAlone(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	binary := filepath.Join(t.TempDir(), "ak")
	build := exec.Command("go", "build", "-mod=vendor", "-o", binary, "./cmd/ak")
	build.Dir = filepath.Join("..", "..")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	call := exec.Command("python3", "-B", "-c", `
import os, sys
from pathlib import Path
os.environ["AK_BIN"] = sys.argv[1]
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures.akbin import Home
from fixtures import akconfig, fakeadapter
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

for edit in ("move", "effort"):
    with Home() as home:
        config = akconfig.write(home, {"fable": "claude", "astra": "codex"})
        adapters = fakeadapter.install(home, claude="pass", codex="pass")
        if edit == "move":
            # Runnable moves now ask in Go; a login refusal still hands over.
            adapters["codex"].answer("auth", "fixture login missing", 1)
        Seat(home, "acme", model="fable", record={"workers": ["astra"], "repo": None})
        record = home.path / ".agentkit/state/session-acme.json"
        # Deliberate whitespace catches even a rewrite of an otherwise equal record.
        record.write_bytes(b"  " + record.read_bytes() + b"\n\n")
        before = (record.read_bytes(), config.read_bytes())
        pane = home.tmux("display-message", "-p", "-t", "=acme:", "#{pane_id} #{pane_pid}").out
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme"})
        term.wait("esc leave", bound=10)
        term.keys("c")
        term.wait(lambda s: "For  acme" in s and "[●]" in s, bound=10)
        term.keys("j" if edit == "move" else "Right")
        term.wait("[○]" if edit == "move" else "␣ step", bound=10)
        term.keys("Space")
        assert term.exit_code() == 3
        after = (record.read_bytes(), config.read_bytes())
        assert after == before, (edit, before, after)
        assert home.tmux("display-message", "-p", "-t", "=acme:", "#{pane_id} #{pane_pid}").out == pane
`, binary)
	call.Dir = filepath.Join("..", "..", "..")
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("restart handoff: %v\n%s", err, out)
	}
}
