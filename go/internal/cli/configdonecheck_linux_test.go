package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

// [defaults] efforts, which Go binds otherwise than Python, hand `Done check`'s page to Python as
// it opens, config.toml as it was.
func TestDoneCheckHandsAnUnboundConfigOverBeforeWriting(t *testing.T) {
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
from fixtures.akterm import Terminal

with Home() as home:
    config = akconfig.write(home, {"fable": "claude", "astra": "codex"})
    config.write_text(config.read_text().replace(
        "[defaults]\n", '[defaults]\nefforts = { fable = { effort = "low" } }\n'))
    fakeadapter.install(home, claude="pass", codex="pass")
    before = config.read_bytes()
    term = Terminal(home, size=(100, 40), env={"NO_COLOR": "1"})
    term.wait("esc leave", bound=10)
    term.keys("c")
    term.wait("› Fable 5.1", bound=10)
    term.keys(*["Down"] * 6)
    term.wait("› Done check", bound=10)
    term.keys("Enter", "Space")
    assert term.exit_code(bound=10) == 3
    assert config.read_bytes() == before
`, binary)
	call.Dir = filepath.Join("..", "..", "..")
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("done check handover: %v\n%s", err, out)
	}
}
