package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

// The sweep behind the first frame is held in tmux, its absence probe of a week-old seat answered
// but not yet handed back, while the owner reopens that seat from the past screen.
func TestTheMenuReopensNoSeatItsOpeningSweepIsForgetting(t *testing.T) {
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
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures.akbin import Home
from fixtures.akterm import Terminal

with Home() as home:
    old = time.time() - 10 * 86400
    home.write(".agentkit/state/session-old-search.json", {
        "orchestrator": "fable", "workers": ["fable"], "cwd": str(home.path), "repo": None,
        "created": old - 3600, "conversation": "conv-old-search", "id_source": "launcher",
        "resumable": True, "session_title": "old-search"})
    home.write(".agentkit/state/seat-old-search.json", {"stopped_at": old, "closed_by_owner": True})
    home.write("adapters/claude.sh", "#!/bin/sh\nprintf '%s' \"sh -c 'echo reopened; exec sleep 300'\"\n").chmod(0o755)
    real = home.bin / "tmux-real"
    (home.bin / "tmux").rename(real)
    held, release = home.root / "held", home.root / "release"
    home.fake("tmux", f"""#!{sys.executable}
import subprocess, sys, time
from pathlib import Path
done = subprocess.run([{str(real)!r}, *sys.argv[1:]], capture_output=True)
if "has-session" in sys.argv and "=old-search" in sys.argv and done.returncode == 1:
    Path({str(held)!r}).touch()
    while not Path({str(release)!r}).exists():
        time.sleep(.01)
sys.stdout.buffer.write(done.stdout)
sys.stderr.buffer.write(done.stderr)
sys.exit(done.returncode)
""")
    menu = Terminal(home, size=(100, 30), env={"AGENTKIT_ADAPTER_DIR": home.path / "adapters"},
                    program=sys.argv[1])
    menu.wait(lambda screen: held.exists() and "p past" in screen)
    menu.keys("p")
    menu.wait(lambda screen: screen.startswith("agentkit · past sessions") and "esc back" in screen)
    menu.keys("Enter")
    time.sleep(1)
    assert home.tmux("has-session", "-t", "=old-search").code != 0, menu.screen()
    release.touch()
    assert menu.exit_code() == 3, menu.screen()      # the seat it chose is gone: Python's to say
    assert home.tmux("has-session", "-t", "=old-search").code != 0, menu.screen()
    assert not (home.path / ".agentkit/state/session-old-search.json").exists()
`, program)
	call.Dir = "../../.."
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("reopened during the sweep: %v\n%s", err, out)
	}
}
