package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

// A model on c while its provider is logged out offers, once that provider is signed in through
// `+ add a subscription`, the efforts its signed-in catalog lists: stepped, it saves one of those.
func TestASignInReadsEveryModelAgain(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	binary := filepath.Join(t.TempDir(), "ak")
	build := exec.Command("go", "build", "-mod=vendor", "-o", binary, "./cmd/ak")
	build.Dir = filepath.Join("..", "..")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	call := exec.Command("python3", "-B", "-c", `
import json, os, shlex, sys, time
from pathlib import Path
os.environ["AK_BIN"] = sys.argv[1]
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from test_key_new_subscription_signs_in_afresh import ADD, LIST_KEYS, PAGE, offered, row_at, title

with Home() as home:
    akconfig.write(home, {"one": {"harness": "claude", "model": "m1", "effort": "low"}})
    script = fakeadapter.install(home, claude="pass")["claude"].script
    real, signed = (shlex.quote(str(path)) for path in (script.with_name("claude-real.sh"), home.root / "signed-in"))
    script.rename(script.with_name("claude-real.sh"))
    # logged out until a login, after which its catalog offers m1 at more efforts
    script.write_text('#!/bin/sh\ncase "$1" in\n'
                      "models) if [ -f " + signed + " ]; then printf 'm1\\tModel One\\tlow medium high max\\n'; "
                      "else printf 'm1\\tModel One\\tlow high\\n'; fi; exit 0 ;;\n"
                      "auth) [ -f " + signed + " ] || { echo 'not logged in'; exit 1; } ;;\n"
                      "login) : > " + signed + " ;;\n"
                      'esac\nexec ' + real + ' "$@"\n')
    script.chmod(0o755)
    Seat(home, "acme", model="one", record={"repo": None})
    record = home.path / ".agentkit/state/session-acme.json"
    term = Terminal(home, "attach", "--overlay", size=(100, 40), env={"AGENTKIT_SESSION": "acme", "NO_COLOR": "1"})
    term.wait("esc leave", bound=10)
    term.keys("c")
    term.wait(lambda s: "Subscriptions" in s and "Reading models" not in s, bound=10)
    term.keys("Down", "Down", "Enter")
    term.wait(lambda s: title(s) == PAGE and row_at(s, "Claude") is not None, bound=10)
    term.keys("Down", "Down")
    term.wait(lambda s: row_at(s, "+ add a subscription", "›") is not None, bound=10)
    term.keys("Enter")
    rows = offered(term.wait(lambda s: title(s) == ADD and LIST_KEYS in s and "Claude II" in offered(s), bound=10))
    term.keys(*["Down"] * rows.index("Claude II"), "Enter")
    term.wait(lambda s: title(s) == PAGE and row_at(s, "Claude II") is not None, bound=10)
    term.keys("Escape")
    term.wait(lambda s: title(s) != PAGE and "Subscriptions" in s and "Reading models" not in s, bound=10)
    term.keys("Up", "Up", "Right", "Right", "Right", "Space")   # one's build effort, stepped once
    deadline = time.monotonic() + 10
    while "exec_effort" not in (efforts := json.loads(record.read_text()).get("efforts", {})).get("one", {}) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert efforts == {"one": {"effort": "low", "exec_effort": "medium"}}, (efforts, term.screen())
`, binary)
	call.Dir = filepath.Join("..", "..", "..")
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("sign-in catalog: %v\n%s", err, out)
	}
}
