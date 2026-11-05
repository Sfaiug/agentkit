package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

func TestMenuNoticesWaitForDraftsAndRestartTheReplacedProgram(t *testing.T) {
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
import os, shlex, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

with Home() as home:
    program, original = home.bin / "ak", home.bin / "original"
    for target in (program, original):
        shutil.copy2(sys.argv[1], target)
    Seat(home, "acme")
    Seat(home, "beta")
    menu = Terminal(home, program=str(program))
    menu.wait("esc leave")
    menu.keys("j")
    menu.wait("› 2  beta")
    menu.keys("n")
    menu.wait("tab models")
    menu.type("draft")
    menu.wait("draft▏")
    notice = home.write(".agentkit/state/update-result", "update: installed new code\n")
    replacement = home.bin / "replacement"
    replacement.write_text('#!/bin/sh\nprintf "%s\\n" "$AK_MENU_CURSOR" > "$HOME/restarted"\n'
                           + 'exec ' + shlex.quote(str(original)) + ' "$@"\n')
    replacement.chmod(0o755)
    os.replace(replacement, program)
    home.write(".agentkit/state/installed-at", f"{time.time()}\n")
    menu.type("s")
    menu.wait("drafts▏")
    assert notice.exists(), "a draft lost its keys to a notice"
    assert not (home.path / "restarted").exists(), "a draft was restarted"
    menu.keys("Escape")
    menu.wait("esc back")
    assert not notice.exists()
    menu.keys("i")
    assert "esc back" in menu.screen(), "an unrelated key dismissed the notice"
    assert not (home.path / "restarted").exists(), "a notice was restarted before it was read"
    menu.keys("Enter")
    menu.wait("esc leave")
    menu.keys("i")
    menu.wait(lambda screen: (home.path / "restarted").exists()
              and "› 2  beta" in screen and "esc leave" in screen)
    assert (home.path / "restarted").read_text() == "beta\n", "restart lost its highlighted seat"
    menu.keys("Escape")
    assert menu.exit_code() == 0

for launch in ("binary", "symlink", "path"):
    with Home() as home:
        program, original = home.bin / "ak", home.bin / "original"
        shutil.copy2(sys.argv[1], original)
        if launch == "binary":
            shutil.copy2(original, program)
        else:
            program.symlink_to(original)
        akconfig.write(home, ["opus"])
        made = int(time.time()) - 900
        Seat(home, "acme", record={"created": made})
        beta = Seat(home, "beta", record={"created": made + 60})
        home.write("beta-after", dict(beta.record, created=made - 60))
        if launch == "path":
            (home.path / "launch").mkdir()
            (home.path / "launch/ak").symlink_to(program)
        menu = Terminal(home, program=program.name if launch == "path" else str(program),
                        env={"PATH": "launch:" + home.env["PATH"]} if launch == "path" else None)
        menu.wait("› 1  acme")
        replacement = home.bin / "replacement"
        replacement.write_text('#!/bin/sh\nprintf "%s\\n" "$AK_MENU_CURSOR" > "$HOME/restarted"\n'
                               + 'cp "$HOME/beta-after" "$HOME/.agentkit/state/session-beta.json"\n'
                               + 'exec ' + shlex.quote(str(original)) + ' "$@"\n')
        replacement.chmod(0o755)
        next_program = replacement
        if launch != "binary":
            next_program = home.bin / "next"
            next_program.symlink_to(replacement)
        os.replace(next_program, program)
        akconfig.write(home, ["opus", "astra"])
        home.write(".agentkit/state/installed-at", f"{time.time()}\n")
        menu.keys("i")
        # the first frame is the read handed over the exec; the read after it moves acme down
        menu.wait(lambda screen: "ChatGPT" in screen and "esc leave" in screen
                  and any(line.startswith("› 2  acme") for line in screen.splitlines()))
        assert (home.path / "restarted").exists(), "restart skipped the replaced launch path"
        assert (home.path / "restarted").read_text() == "acme\n", "restart lost the initial highlight"
        menu.keys("Escape")
        assert menu.exit_code() == 0
`, program)
	call.Dir = "../../.."
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("notices and replaced program: %v\n%s", err, out)
	}
}
