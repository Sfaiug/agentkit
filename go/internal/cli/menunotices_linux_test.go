package cli

import (
	"context"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestMenuNoticesWaitForDraftsAndRestartTheReplacedProgram(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	t.Setenv("HOME", t.TempDir())
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	program := filepath.Join(t.TempDir(), "ak")
	build := exec.CommandContext(ctx, "go", "build", "-o", program, "./cmd/ak")
	build.Dir = "../.."
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	call := exec.CommandContext(ctx, "python3", "-B", "-c", `
import os, shlex, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path("tests").resolve()))
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
`, program)
	call.Dir = "../../.."
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("notices and replaced program: %v\n%s", err, out)
	}
}
