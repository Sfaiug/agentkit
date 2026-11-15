package cli

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

// A look at every seat waits on each one's announce lock, which another reader holds as long as
// its own look takes: the words as recorded and a seat that appears are on the screen meanwhile,
// and the look's own findings once it ends.
func TestNewsIsShownWhileALookWaitsOnASeat(t *testing.T) {
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", t.TempDir())
	call := exec.Command("python3", "-B", "-c", `
import fcntl, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

def row(name, word):
    return lambda screen: re.search(rf"^[› ] +\d+  {re.escape(name)} .*{word}", screen, re.M)

def recorded(name):
    seat = state / f"seat-{name}.json"
    return json.loads(seat.read_text()) if seat.exists() else {}

with Home() as home:
    Seat(home, "acme")
    state = home.path / ".agentkit/state"
    menu = Terminal(home, "-test.run=^TestMenuOpeningProgram$", size=(100, 40),
                    env={"AK_TEST_MENU_OPEN": "1"}, program=sys.argv[1])
    menu.wait(row("acme", "idle"))
    menu.wait(lambda _: recorded("acme").get("word") == "idle")   # the first look wrote it down
    with open(state / "seat-beta.announce", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        Seat(home, "beta")
        home.write(".agentkit/state/seat-acme.json", {**recorded("acme"), "word": "needs you"})
        menu.wait(lambda screen: row("acme", "needs you")(screen) and row("beta", "")(screen))
    menu.wait(row("acme", "idle"))   # the look that waited saw acme's pane
`, self)
	call.Dir = filepath.Join("..", "..", "..")
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("news behind a held look: %v\n%s", err, out)
	}
}
