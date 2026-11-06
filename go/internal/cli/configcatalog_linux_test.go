package cli

import (
	"os/exec"
	"path/filepath"
	"testing"
)

func TestConfigCatalogWaitDrawsFirstAndEscReapsTheBlockedAdapter(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	binary := filepath.Join(t.TempDir(), "ak")
	build := exec.Command("go", "build", "-mod=vendor", "-o", binary, "./cmd/ak")
	build.Dir = filepath.Join("..", "..")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	call := exec.Command("python3", "-B", "-c", `
import errno, os, shlex, sys
from pathlib import Path
os.environ["AK_BIN"] = sys.argv[1]
sys.path.insert(0, str(Path("tests").resolve()))
from fixtures.akbin import Home
from fixtures import akconfig, fakeadapter
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

for page, colour, size in (("config", False, (100, 30)), ("models", False, (100, 30)),
                           ("config", True, (100, 30)), ("config", False, (60, 12)),
                           ("config", False, (18, 9)), ("config", False, (60, 7))):
    with Home() as home:
        models = {"fable": "claude", "astra": "codex"}
        if size[1] < 30:
            models.update(spark="muse", grok="grokbuild", gemini="antigravity", mimo="opencode")
        cfg = akconfig.write(home, models)
        adapters = fakeadapter.install(home, **dict.fromkeys(models.values(), "pass"))
        Seat(home, "acme", model="fable", record={"workers": ["astra"], "repo": None})
        record = home.path / ".agentkit/state/session-acme.json"
        before = (cfg.read_bytes(), record.read_bytes())
        marker, release, seen = (home.root/name for name in ("started", "release", "seen"))
        os.mkfifo(release)
        script = adapters["claude"].script
        real = script.with_name("claude-real.sh")
        script.rename(real)
        gate = ': > ' + shlex.quote(str(marker)) + '\nread token < ' + shlex.quote(str(release)) + '\n'
        if page == "models":
            gate = 'if [ -f ' + shlex.quote(str(seen)) + ' ]; then\n' + gate + 'else\n: > ' + shlex.quote(str(seen)) + '\nfi\n'
        script.write_text('#!/bin/sh\nif [ "$1" = models ]; then\n' + gate +
                          "printf 'm1\\tModel One\\tlow high\\n'\nelse\nexec " +
                          shlex.quote(str(real)) + ' "$@"\nfi\n')
        script.chmod(0o755)
        env = {"AGENTKIT_SESSION": "acme", **({"COLORTERM": "truecolor"} if colour else {"NO_COLOR": "1"})}
        term = Terminal(home, "attach", "--overlay", size=size, env=env)
        term.wait("esc leave", bound=10)
        try:
            term.keys("c")
            if page == "models":
                term.wait("For  acme", bound=10)
                term.keys("j", "j", "Enter")
                term.wait("config · models", bound=10)
                term.keys("Enter")
            shown = term.wait(lambda s: marker.exists() and "Reading models" in s, bound=10)
            assert shown.splitlines()[0].startswith("agentkit") and "esc back" in shown and "Reading models" in shown, shown
            if size[0] >= 60:
                assert "agentkit · config" in shown.splitlines()[0], shown
            if colour:
                rule = shown.splitlines()[1]
                term.wait(lambda s: s.splitlines()[1] != rule, bound=3)
            term.keys("Escape")
            if page == "models":
                # the list opens saying so, as Python's does (menu.models_page), and Esc shuts it
                term.wait(lambda s: "not read: esc and open it again" in s and "Reading models" not in s, bound=3)
                term.keys("Escape")
                term.wait(lambda s: "config · models" in s and "not read" not in s, bound=3)
                term.keys("Escape")
                term.wait("For  acme", bound=3)
            else:
                term.wait("esc leave", bound=3)
            # No FIFO reader remains after Esc: cancellation reaped the adapter before returning.
            try:
                fd = os.open(release, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                assert exc.errno == errno.ENXIO, exc
            else:
                os.close(fd)
                raise AssertionError("the adapter is still waiting on its FIFO")
            assert (cfg.read_bytes(), record.read_bytes()) == before, page
        finally:
            try:
                fd = os.open(release, os.O_WRONLY | os.O_NONBLOCK)
                os.write(fd, b"go\n")
                os.close(fd)
            except OSError:
                pass
`, binary)
	call.Dir = filepath.Join("..", "..", "..")
	if out, err := call.CombinedOutput(); err != nil {
		t.Fatalf("catalog wait: %v\n%s", err, out)
	}
}
