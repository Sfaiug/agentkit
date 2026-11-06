package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

func TestModelsPickerClicksOnlyItsDrawnLabels(t *testing.T) {
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
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from fixtures.akterm import Terminal
from test_key_models_answer import ENV, boards

for target, marked in (("all 4 models", None),
                       ("Acme Mid 5", ["acme-mid-5", "bolt-3"])):
    with Home() as home:
        adapters = fakeadapter.install(home, claude="pass", codex="pass")
        adapters["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        adapters["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\n")
        config = akconfig.write(home, {
            "mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
            "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}},
            settings={"compare": ["bolt-3"]})
        held = boards()
        for row in held["artificialanalysis.ai"]["rows"]:
            row["maker"] = row["model"].split()[0]
        home.write(".agentkit/state/boards.json", held)
        term = Terminal(home, size=(100, 40), env=ENV)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait("boards read")
        term.keys("p")
        shown = term.wait(lambda screen: screen.rstrip().endswith("esc done"))
        row = next(i for i, line in enumerate(shown.splitlines()) if target in line) + 1
        before = config.read_bytes()
        term.type(f"\x1b[<0;95;{row}M\x1b[<0;95;{row}m")
        # Typing and erasing a find proves the click was read before checking disk.
        term.type("mid")
        term.wait("find  mid")
        assert config.read_bytes() == before, target
        term.keys("BSpace", "BSpace", "BSpace")
        shown = term.wait(lambda screen: "find  ▏" in screen and "Crux 2" in screen)
        line = next(line for line in shown.splitlines() if target in line)
        row = shown.splitlines().index(line) + 1
        column = line.index(target) + 1
        term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")
        term.wait("all 4 compared" if marked is None else "2 of 4 marked")
        assert akconfig.read(home).get("compare") == marked, target
`, binary)
	call.Dir = filepath.Join("..", "..", "..")
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("picker clicks: %v\n%s", err, out)
	}
}
