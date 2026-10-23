"""A harness adapter with no model behind it: each turn does and hands in what the test scripts.

`install` puts `<harness>.sh` and `<harness>.toml` in `<root>/adapters` and names that directory
in the Home's AGENTKIT_ADAPTER_DIR, so every ak the test runs from then on calls these and no
real harness.  The toml is the shipped manifest with the directory as its `[worker] state`, the
one place a worker's box lets a turn write beside its workspace.  The script runs this file.

A harness's script is a list of steps, one per `run` call in order, the last repeated.  A step
is a word, which acts by the turn's role as its prompt's first line names it:

    word        executor             fixer                reviewer
    work        writes and commits   as executor          hand-in done
                retry.txt, done
    pass        hand-in done, no change
    fail        as work              as work              hand-in finding retry.txt:1, done
    dispute     as work              hand-in dispute      hand-in done
                                     retry.txt:1, done
    blocked     hand-in blocked "the fixture needs the owner", in any role (a review
                turn refuses it)
    not-needed  hand-in not-needed "the fixture found nothing to do", as blocked
    silent      an empty final.md, no hand-in, exit 0
    flaky       final.md 'API Error: 500 {"type":"error"}', exit 1
    dead        final.md 'You have hit your usage limit.', exit 1

or a dict of what to do, in this order: `write` {path: text} (a relative path is in the
workspace), `sh` (a command run there), `commit` (a message for all of it), `hand_in` (a list
of argument lists for `ak hand-in`), `final` (final.md's text, where `{in N}` is the moment N
seconds after the turn, as a refusal names when to come back), `session` (the id handed back:
the one resumed, else `sid-<harness>-<n>`), `exit` (0).  A hand-in goes through the ak build
under test, the one AK_BIN names.  Every other verb answers as `answer` set it, or as a harness
that is logged in with no meter to read, except that `interactive` refuses an id for a new
conversation (exit 3) where the shipped adapter does, as Codex's TUI takes none.

Each harness's Adapter: `n` counts its `run` calls, `runs()` and `calls(verb)` read its log,
`behave(*steps)` scripts its next turns, `answer(verb, out, code)` sets what another verb
prints, and `dir`, `script` and `manifest` are its files.  A file in `dir` is one a turn and
the test both see, such as a release a step's `sh` waits for.

    from fixtures.akbin import Home
    from fixtures import fakeadapter
    with Home() as home:
        fakes = fakeadapter.install(home, claude="work", codex=["fail", "pass"])
        home.ak("run", "task.md", "--no-merge")
        assert fakes["codex"].n == 2
        assert fakes["codex"].runs()[0]["hand_ins"][0]["code"] == 0
"""

import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
IDENTITY = {"GIT_AUTHOR_NAME": "acme", "GIT_AUTHOR_EMAIL": "acme@example.com",
            "GIT_COMMITTER_NAME": "acme", "GIT_COMMITTER_EMAIL": "acme@example.com"}
WORK = {"write": {"retry.txt": "hello\n"}, "commit": "add retry.txt",
        "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
PASS = {"final": "Handed in.", "hand_in": [["done"]]}
FAIL = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fixture defect", "the fixture says so", "--run",
     "test ! -f retry.txt"], ["done"]]}
DISPUTE = {"final": "Disputed.", "hand_in": [
    ["dispute", "retry.txt:1", "not a defect", "--run", "true"], ["done"]]}


def _every(step):
    return {"executor": step, "fixer": step, "reviewer": step}


WORDS = {"work": {**_every(WORK), "reviewer": PASS}, "pass": _every(PASS),
         "fail": {**_every(WORK), "reviewer": FAIL},
         "dispute": {"executor": WORK, "fixer": DISPUTE, "reviewer": PASS},
         "blocked": _every({"final": "Blocked.",
                            "hand_in": [["blocked", "the fixture needs the owner"]]}),
         "not-needed": _every({"final": "Not needed.",
                               "hand_in": [["not-needed", "the fixture found nothing to do"]]}),
         "silent": _every({}),
         "flaky": _every({"final": 'API Error: 500 {"type":"error"}', "exit": 1}),
         "dead": _every({"final": "You have hit your usage limit.", "exit": 1})}
# How a shipped adapter refuses a conversation id of ak's making for a TUI that takes none.
NEW_ID_REFUSED = '[ "${4:-}" = new ] && {'
ANSWERS = {"usage": '{"meters": [], "error": "unknown: fake"}', "auth": "the fake needs no login",
           "interactive": "sleep 600", "login-end": '{"email": null, "ends": null}',
           "models": ""}


class Adapter:
    def __init__(self, directory, harness):
        self.harness, self.dir = harness, directory
        self.script = directory / f"{harness}.sh"
        self.manifest = directory / f"{harness}.toml"

    def behave(self, *steps):
        """Script the turns from the next `run` call on."""
        self._put("beh", json.dumps({"from": self.n, "steps": list(steps)}))

    def answer(self, verb, out, code=0):
        """What a verb other than `run` prints, and its exit status, from now on."""
        answers = self._json("answers") or {}
        self._put("answers", json.dumps({**answers, verb: [out, code]}))

    @property
    def n(self):
        """`run` calls so far, finished or not."""
        return self._json("n") or 0

    def calls(self, verb=None):
        """Each finished call, oldest first: its `verb`, `argv`, `cwd` and the AK_* and
        AGENTKIT_* part of its `env`; a `run` also has its `n`, `role`, `step` and `hand_ins`,
        each with its `argv`, `code`, `out` and `err`."""
        try:
            rows = [json.loads(line) for line in self._file("calls").read_text().splitlines()]
        except FileNotFoundError:
            return []
        return [row for row in rows if verb in (None, row["verb"])]

    def runs(self):
        return self.calls("run")

    def _file(self, kind):
        return self.dir / f"{self.harness}.{kind}"

    def _put(self, kind, text):
        """A file the test and a turn both read, replaced whole: a reader never sees it empty."""
        part = self._file(kind).with_name(f"{self._file(kind).name}.{os.getpid()}")
        part.write_text(text)
        part.replace(self._file(kind))

    def _json(self, kind):
        try:
            return json.loads(self._file(kind).read_text())
        except FileNotFoundError:
            return None


def install(home, **harnesses):
    """A fresh fake for each harness named, scripted with a step or a list of them; the
    Adapters by harness."""
    from .akbin import AK    # here: a turn runs this file as a script, outside the package
    directory = home.root / "adapters"
    directory.mkdir(exist_ok=True)
    home.env["AGENTKIT_ADAPTER_DIR"] = str(directory)
    fakes = {}
    for harness, steps in harnesses.items():
        fake = fakes[harness] = Adapter(directory, harness)
        for kind in ("n", "calls", "answers"):
            fake._file(kind).unlink(missing_ok=True)
        fake.behave(*(steps if isinstance(steps, list) else [steps]))
        fake.script.write_text("#!/bin/sh\nexec " + shlex.join(
            [sys.executable, "-I", __file__, str(directory), harness, AK]) + ' "$@"\n')
        fake.script.chmod(0o755)
        shipped = REPO / "adapters" / f"{harness}.toml"
        text = shipped.read_text() if shipped.exists() else "version = 1\n"
        text = re.sub(r"(?ms)^\[worker\]\n.*?(?=^\[|\Z)", "", text).rstrip()
        fake.manifest.write_text(f"{text}\n\n[worker]\nstate = {json.dumps([str(directory)])}\n")
    return fakes


def main(directory, harness, ak, verb="", *args):
    fake = Adapter(Path(directory), harness)
    call = {"verb": verb, "argv": list(args), "cwd": os.getcwd(),
            "env": {k: v for k, v in os.environ.items() if k.startswith(("AK_", "AGENTKIT_"))}}
    shipped = REPO / "adapters" / f"{harness}.sh"
    if (verb == "interactive" and args[3:4] == ("new",) and shipped.is_file()
            and NEW_ID_REFUSED in shipped.read_text()):
        print(f"{harness}.sh interactive: the TUI cannot be given a thread id", file=sys.stderr)
        code = 3
    elif verb != "run":
        out, code = (fake._json("answers") or {}).get(verb) or [
            ANSWERS.get(verb, f"fake {harness}: {verb}"), 0]
        print(out)
    else:
        code = turn(fake, ak, call, *args)
    with fake._file("calls").open("a") as log:
        log.write(json.dumps(call) + "\n")
    return code


def turn(fake, ak, call, model, effort, workspace, prompt, out, session=None):
    # turns at once each take a number of their own
    with fake._file("lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        n = fake.n + 1
        fake._put("n", str(n))
    first = Path(prompt).read_text().split("\n", 1)[0]
    role = ("reviewer" if first.startswith("You are the reviewer") else
            "fixer" if first.startswith("You are the executor, continuing") else "executor")
    script = fake._json("beh")
    step = script["steps"][min(n - script["from"], len(script["steps"])) - 1]
    todo = WORDS[step][role] if isinstance(step, str) else step
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stderr.log").write_text(f"fake {fake.harness} adapter, call {n}\n")
    (out / "session_id").write_text(todo.get("session", session or f"sid-{fake.harness}-{n}"))
    for relative, text in todo.get("write", {}).items():
        path = Path(workspace, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git = {**os.environ, **IDENTITY}
    if "sh" in todo:
        # A process it leaves behind must not hold this turn's output open.
        subprocess.run(["sh", "-c", todo["sh"]], cwd=workspace, env=git,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    if "commit" in todo:
        subprocess.run(["git", "add", "-A"], cwd=workspace, env=git, capture_output=True)
        subprocess.run(["git", "commit", "-qm", todo["commit"]], cwd=workspace, env=git,
                       capture_output=True)
    call.update(n=n, role=role, step=step, hand_ins=[])
    for argv in todo.get("hand_in", ()):
        done = subprocess.run([ak, "hand-in", *argv], cwd=workspace, capture_output=True,
                              text=True)
        call["hand_ins"].append({"argv": argv, "code": done.returncode, "out": done.stdout,
                                 "err": done.stderr})
    # counted from the turn: a moment fixed before the run could pass before a slow run gets here
    final = re.sub(r"\{in (\d+)\}", lambda m: time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + int(m[1]))), todo.get("final", ""))
    (out / "final.md").write_text(final + "\n" if final else "")
    return todo.get("exit", 0)


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
