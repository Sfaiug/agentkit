"""Run an ak program from outside, the way a person, a model or a harness does.

The answer key's tests judge ak only by its exit code, what it prints and what it writes, so one
test holds whichever build `AK_BIN` names: this checkout's `bin/ak` when unset, and a relative
name is read from the checkout.  Nothing here imports agentkit.

`Home` is a throwaway HOME for the program, with the shipped `config.default.toml` as its config.
The program sees a scrubbed environment, never the caller's: no `AK_*`, `AGENTKIT_*`, tmux or
harness variable reaches it, so it is nobody's seat or run and can find no login; its tmux socket
directory is private; notifications go nowhere; and `home.bin` leads PATH.  There a fake `tmux`
and `gh` log each call and refuse it, so no test reaches a real server or GitHub unless it puts
a fake of its own there with `home.fake`.

    from fixtures.akbin import Home
    with Home() as home:
        done = home.ak("run", "-h")
        assert done.code == 0, done.err
"""

from collections import namedtuple
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
_NAMED = Path(os.environ.get("AK_BIN") or "bin/ak")
AK = str(_NAMED if _NAMED.is_absolute() else REPO / _NAMED)

Done = namedtuple("Done", "code out err")

# One JSON argv per line, then a refusal: the default for every fake a test does not script.
REFUSE = """#!/bin/sh
{python} -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >>{log}
echo "{name}: not scripted in this test" >&2
exit 1
"""


class Home:
    """A throwaway HOME the program runs in; `close` (or leaving `with`) removes it."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="akbin-"))
        self.path = self.root / "home"
        self.bin = self.root / "bin"
        for directory in (self.path / ".agentkit" / "state", self.bin, self.root / "tmux",
                          self.root / "tmp", self.root / "logs"):
            directory.mkdir(parents=True)
        shutil.copy(REPO / "config.default.toml", self.path / ".agentkit" / "config.toml")
        for name in ("tmux", "gh"):
            self.fake(name, REFUSE.format(python=shlex.quote(sys.executable), name=name,
                                          log=shlex.quote(str(self.log(name)))))
        self.env = {
            "HOME": str(self.path),
            "PATH": os.pathsep.join([str(self.bin), str(Path(sys.executable).parent),
                                     "/usr/local/bin", "/usr/bin", "/bin"]),
            "USER": os.environ.get("USER", "acme"), "LOGNAME": os.environ.get("LOGNAME", "acme"),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb",
            "TMPDIR": str(self.root / "tmp"), "TMUX_TMPDIR": str(self.root / "tmux"),
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "AK_NOTIFY_SINK": "dry-run",
            # nobody's nested run, and no slot gate parking a launch behind the host's load
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
        }

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def log(self, name):
        return self.root / "logs" / f"{name}.log"

    def fake(self, name, script):
        """Put an executable `name` first on the program's PATH."""
        path = self.bin / name
        path.write_text(script)
        path.chmod(0o755)
        return path

    def calls(self, name):
        """Each argv a refusing fake was called with, oldest first."""
        try:
            return [json.loads(line) for line in self.log(name).read_text().splitlines()]
        except FileNotFoundError:
            return []

    def ak(self, *args, input=None, env=None, cwd=None, timeout=120):
        """Run the program once; a hang fails the test, naming the command, and leaves nothing
        of it running."""
        proc = subprocess.Popen([AK, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, cwd=cwd or self.path,
                                env={**self.env, **(env or {})}, start_new_session=True)
        try:
            out, err = proc.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise AssertionError(f"still running after {timeout} s: ak {shlex.join(args)}") from None
        return Done(proc.returncode, out, err)
