package cli

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestMenuOpeningProgram(t *testing.T) {
	if os.Getenv("AK_TEST_MENU_OPEN") == "" {
		t.Skip("run by TestMenuTerminationWhileVisiting")
	}
	os.Exit(Main(nil, os.Stdout, os.Stderr))
}

func TestMenuTerminationWhileVisiting(t *testing.T) {
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", t.TempDir())
	call := exec.Command("python3", "-B", "-c", `
import os, signal, sys, time
from pathlib import Path
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

for ending, visiting in ((signal.SIGTERM, True), (signal.SIGHUP, True),
                        (signal.SIGTERM, False), (signal.SIGHUP, False)):
    with Home() as home:
        Seat(home, "acme")
        menu = Terminal(home, "-test.run=^TestMenuOpeningProgram$", size=(100, 40),
                        env={"AK_TEST_MENU_OPEN": "1"}, program=sys.argv[1])
        menu.wait("esc leave")
        pid = int(menu._ask("display-message", "-p", "-t", menu.pane, "#{pane_pid}"))
        while Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")[0] != os.fsencode(sys.argv[1]):
            pid = int(Path(f"/proc/{pid}/task/{pid}/children").read_text().split()[0])
        menu.keys("1")
        deadline = time.monotonic() + 10
        while not home.tmux("list-clients", "-F", "#{client_session}").out.split():
            assert time.monotonic() < deadline, "no client attached"
            time.sleep(.05)
        if not visiting:
            home.tmux("detach-client", "-s", "=acme")
            menu.wait("esc leave")
        os.kill(pid, ending)
        code = menu.exit_code(bound=3)
        assert code == 128 + ending, (ending, code)
        if not visiting:
            modes = menu._ask("display-message", "-p", "-t", menu.pane,
                              "#{alternate_on} #{cursor_flag} #{mouse_any_flag} #{mouse_sgr_flag}")
            assert modes.strip() == "0 1 0 0", modes
`, self)
	call.Dir = filepath.Join("..", "..", "..")
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("menu signal regression: %v\n%s", err, out)
	}
}
