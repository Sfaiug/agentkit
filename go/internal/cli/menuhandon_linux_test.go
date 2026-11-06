package cli

import (
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"

	"agentkit/internal/menu"
)

// handing sets this program's environment as an exec handed it data would.
func handing(t *testing.T, data []byte) {
	name, value, _ := strings.Cut(cross(menuRead, data)[0], "=")
	t.Setenv(name, value)
}

func TestAReadCrossesAnExecOnlyToTheSameCodeAndOnlyOnce(t *testing.T) {
	found := reading{seats: []menu.Seat{{Number: 1, Name: "acme", Word: "idle", Done: 1, Total: 2}},
		cells: []menu.Cell{{Label: "Claude", Left: 40}}, standing: "a token ends soon",
		past: []menu.PastSeat{{Seat: menu.Seat{Name: "fix-api"}, Closed: 1.5}}}
	handing(t, handOn(found))
	if got, ok := handedRead(); !ok || !reflect.DeepEqual(got, found) {
		t.Fatalf("handed %+v %v", got, ok)
	}
	if _, set := os.LookupEnv(menuRead); set {
		t.Fatal("the variable stayed for what this program starts")
	}
	if _, ok := handedRead(); ok {
		t.Fatal("a read crossed twice")
	}
	for _, made := range [][]byte{pickled("python's code", []byte("{}")), []byte("\x80\x04garbage"), handOn(found)[:9]} {
		handing(t, made)
		if _, ok := handedRead(); ok {
			t.Fatalf("took %q", made)
		}
	}
	other, _, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv(menuRead, strconv.Itoa(int(other.Fd())))
	if crossed(menuRead); other.Close() != nil {
		t.Fatal("a descriptor no cross made was closed")
	}
}

func TestARestartsRowsStayUpThroughAReadNoReadWasHandedForWhichCtrlCStillCuts(t *testing.T) {
	program := filepath.Join(t.TempDir(), "ak")
	build := exec.Command("go", "build", "-o", program, "./cmd/ak")
	build.Dir = "../.."
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	// run.json, a pipe nobody writes, holds the read for good: what shows came before it
	call := exec.Command("python3", "-B", "-c", `
import fcntl, os, select, signal, struct, subprocess, sys, tempfile, termios, time
from pathlib import Path
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures.akbin import Home

with Home() as home, tempfile.TemporaryFile() as frame:
    run = home.path / ".agentkit/runs/fix-api/run.json"
    run.parent.mkdir(parents=True)
    os.mkfifo(run)
    frame.write(b"80 24\nacme old frame")
    frame.seek(0)
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    found = termios.tcgetattr(slave)
    env = home._env({"TERM": "xterm-256color", "AK_MENU_CURSOR": "acme",
                     "AK_MENU_FRAME": str(frame.fileno())})
    proc = subprocess.Popen([sys.argv[1]], cwd=home.path, env=env, stdin=slave, stdout=slave,
                            stderr=slave, pass_fds=[frame.fileno()], start_new_session=True)
    seen, deadline = b"", time.monotonic() + 30
    try:
        while b"acme old frame\x1b[K\x1b[?2026l" not in seen:
            assert time.monotonic() < deadline and proc.poll() is None, seen
            if select.select([master], [], [], 0.1)[0]:
                seen += os.read(master, 65536)
        os.kill(proc.pid, signal.SIGINT)
        assert proc.wait(timeout=10) == 128 + signal.SIGINT
        assert termios.tcgetattr(slave) == found, "Ctrl-C left the terminal taken"
    finally:
        proc.kill()
        proc.wait()
`, program)
	call.Dir = "../../.."
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("rows before the read: %v\n%s", err, out)
	}
}
