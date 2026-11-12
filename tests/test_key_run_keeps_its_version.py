"""A run keeps the ak it was admitted on for its rounds and hand-ins; its landing runs the install.

Each version of the install holds this test's `bin/ak` (`AK`), which notes its commit and its
arguments, then runs that version's program, kept beside it.  A round's version is the commit of
the `ak` its worker is handed, which each executor turn writes down (`HANDED`): the Home's PATH
holds none, so it can only be ak's.  A hand-in's is what the `ak` it ran noted, one note for each
hand-in a turn made.  A lander may start its program by any path, so its version is read from its
process while a landing check holds it (`HELD`): the checkout holding its executable, or else its
script."""

import json
import os
from pathlib import Path
import shlex
import signal
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, rerun_boxed
from fixtures.akinstall import Install
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# A script runs in this process, as `python3 bin/ak` ran this one, so it still sees itself as
# bin/ak, the name Python's tells a run's own process by; a binary replaces this process.
AK = '''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
program = Path(__file__).resolve().with_name("program")
commit = subprocess.run(["git", "-C", program.parent, "rev-parse", "HEAD"], capture_output=True,
                        text=True).stdout.strip()
with open({noted!r}, "a") as noted:
    noted.write(json.dumps([commit, *sys.argv[1:]]) + "\\n")
with program.open("rb") as start:
    script = start.read(2) == b"#!"
if script:
    __file__ = str(program)
    exec(compile(program.read_bytes(), __file__, "exec"))
else:
    os.execv(program, sys.argv)
'''
HANDED = 'git -C "$(dirname "$(command -v ak)")" rev-parse HEAD >>{}'
# Only a landing runs a `# once` check.  A box may hide the Home's files from it, never its
# processes from the test, which ends this sleep once it has read the lander's process.  The
# sleep is named by `holder`, so the test holds no other Home's landing and ends no other sleep.
HELD = "(exec -a {} sleep 120); true # once"


def holder(home):
    """The name of the sleep `HELD` runs in `home`: a path inside it, which no other Home holds."""
    return str(home.root / "landing-held")


def wait_for(read):
    until = time.monotonic() + 120
    while not (value := read()) and time.monotonic() < until:
        time.sleep(0.1)
    assert value, "the run did not reach its next step"
    return value


def ended(directory):
    """The run's record, once the run has ended."""
    state = json.loads((directory / "run.json").read_text())
    if state.get("state") in ("pass", "fail", "error", "blocked", "exhausted"):
        return state


def notes(noted):
    """What each version's `ak` noted, oldest first."""
    return [json.loads(line) for line in noted.read_text().splitlines()]


def handed_in(notes):
    """The hand-ins among `notes`."""
    return sorted(note for note in notes if note[1:2] == ["hand-in"])


def hand_ins(fakes, commit):
    """Each hand-in the fakes' turns made, as the `ak` of `commit` notes it."""
    return sorted([commit, "hand-in", *hand["argv"]] for fake in fakes.values()
                  for call in fake.runs() for hand in call["hand_ins"])


def processes():
    """Each process's id, arguments and executable, as /proc shows them."""
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="replace").split("\0")[:-1]
        except OSError:
            continue    # gone
        try:
            exe = os.readlink(proc / "exe")
        except OSError:
            exe = ""    # a kernel thread's, or gone
        yield int(proc.name), argv, exe


def landing(home):
    """The commits the Home's landers run while `HELD` holds a landing, which then goes on."""
    held = wait_for(lambda: [pid for pid, argv, _ in processes() if argv[:1] == [holder(home)]])
    commits = set()
    for _, argv, exe in processes():
        if any(argv[at:at + 2] == ["run", "--lander"] for at in range(len(argv))):
            program = next((path.resolve() for path in map(Path, (exe, *argv))
                            if path.is_absolute() and path.resolve().is_relative_to(home.root)),
                           None)
            if program:
                commits.add(home.run("git", "-C", str(program.parent), "rev-parse", "HEAD")
                            .out.strip())
    for pid in held:
        os.kill(pid, signal.SIGTERM)
    return commits


class RunKeepsItsVersion(unittest.TestCase):
    def test_rounds_and_hand_ins_keep_the_admitted_commit_while_landing_uses_the_install(self):
        with Home() as home:
            install = Install(home)
            # where a worker's box lets a turn, and the hand-in it runs, write
            noted, handed = home.root / "adapters/noted", home.root / "adapters/handed"
            ak = install.seed / "bin/ak"
            ak.rename(ak.with_name("program"))
            ak.write_text(AK.format(noted=str(noted)))
            ak.chmod(0o755)
            first = install._push("note each step's ak version")
            install.git("fetch", "-q", "origin")
            install.git("reset", "--hard", first)
            akconfig.write(home, ["opus", "astra"])
            rig = Rig(home, "widgets")
            gh = GitHub(home)
            gh.grant(rig.slug, "WRITE")
            release = home.root / "adapters/release"
            hand = HANDED.format(shlex.quote(str(handed)))
            wait = f"while [ ! -f {shlex.quote(str(release))} ]; do sleep 0.1; done"
            held = {**fakeadapter.WORK, "write": {"retry.txt": "hello\n", "fault.txt": "fault\n"},
                    "sh": f"timeout 120 sh -c '{wait}'; {hand}"}
            failure = {**fakeadapter.FAIL, "hand_in": [["finding", "fault.txt:1", "fixture defect",
                       "blocks delivery", "--run", "test ! -f fault.txt"], ["done"]]}
            fixed = {**fakeadapter.WORK, "sh": f"rm fault.txt; {hand}"}
            fakes = fakeadapter.install(home, claude=[held, fixed], codex=[failure, "pass"])
            done_when = ("test -f retry.txt", HELD.format(shlex.quote(holder(home))))
            task = taskfile.write(home, rig.path, done_when=done_when)
            done = home.run(install.ak, "run", str(task), "--bg", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            directory = taskfile.only_run(home)
            wait_for(lambda: fakes["claude"].n == 1)
            second = install.advance()
            tick = home.run(install.ak, "watch", timeout=300)
            self.assertEqual(tick.code, 0, tick.out + tick.err)
            self.assertEqual(install.head(), second)
            release.touch()
            self.assertEqual(landing(home), {second})
            state = wait_for(lambda: ended(directory))
            self.assertTrue(state.get("merged"), (directory / "log.txt").read_text()
                            + str([call["hand_ins"] for fake in fakes.values() for call in fake.runs()]))
            self.assertNotIn("pickup", state)
            self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL", "PASS"])
            older = notes(noted)
            self.assertEqual(handed_in(older), hand_ins(fakes, first), older)
            self.assertEqual(handed.read_text().split(), [first, first])
            rig = Rig(home, "gears")
            gh.grant(rig.slug, "WRITE")
            fakes = fakeadapter.install(home, claude={**fakeadapter.WORK, "sh": hand}, codex="pass")
            task = taskfile.write(home, rig.path, "Another retry file", done_when=done_when)
            done = home.run(install.ak, "run", str(task), "--bg", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            newer = next(path for path in taskfile.runs(home) if path != directory)
            self.assertEqual(landing(home), {second})
            self.assertTrue(wait_for(lambda: ended(newer)).get("merged"),
                            (newer / "log.txt").read_text())
            self.assertEqual(handed_in(notes(noted)[len(older):]), hand_ins(fakes, second),
                             notes(noted))
            self.assertEqual(handed.read_text().split(), [first, first, second])


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
