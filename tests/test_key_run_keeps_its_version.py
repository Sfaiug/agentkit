"""An install between rounds changes only runs admitted after it, through landing.

Black-box: AK_BIN's live copy, real git swaps, and scripted workers. Each observed step
lazily imports a probe from its own checkout and writes that checkout's commit.
"""

import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, rerun_boxed
from fixtures.akinstall import Install
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

PROBE = '''from pathlib import Path
import subprocess
from . import config

def note(path):
    sha = subprocess.check_output(["git", "-C", str(config.REPO), "rev-parse", "HEAD"], text=True)
    Path(path).write_text(sha)
'''
OBSERVE = {
    "roundloop": '''
_execute_before_probe = execute
def execute(lp, *args, **kwargs):
    from .version_probe import note
    note(lp.run_dir / f"round-{lp.rnd}.code")
    return _execute_before_probe(lp, *args, **kwargs)
''',
    "land": '''
_check_before_probe = _check
def _check(directory, *args, **kwargs):
    from .version_probe import note
    note(directory / "landing.code")
    return _check_before_probe(directory, *args, **kwargs)
''',
    "hand_in": '''
_main_before_probe = main
def main(argv):
    from .version_probe import note
    note(Path(os.environ[ENV]).with_name("ak.code"))
    return _main_before_probe(argv)
'''}


def wait_for(read):
    until = time.monotonic() + 120
    while not (value := read()) and time.monotonic() < until:
        time.sleep(0.1)
    assert value, "the run did not reach its next step"
    return value


class RunKeepsItsVersion(unittest.TestCase):
    def test_rounds_hand_ins_gate_and_landing_keep_the_admitted_commit(self):
        with Home() as home:
            install = Install(home)
            for module, text in OBSERVE.items():
                with (install.seed / "agentkit" / f"{module}.py").open("a") as out:
                    out.write(text)
            (install.seed / "agentkit/version_probe.py").write_text(PROBE)
            first = install._push("observe each step's ak checkout")
            install.git("fetch", "-q", "origin")
            install.git("reset", "--hard", first)
            akconfig.write(home, ["opus", "astra"])
            rig = Rig(home, "widgets")
            gh = GitHub(home)
            gh.grant(rig.slug, "WRITE")
            release = home.root / "adapters/release"
            held = {**fakeadapter.WORK, "sh":
                    f"timeout 120 sh -c 'while [ ! -f {shlex.quote(str(release))} ]; do sleep 0.1; done'"}
            fakes = fakeadapter.install(home, claude=[held, "work"], codex=["fail", "pass"])
            task = taskfile.write(home, rig.path)
            done = home.run(install.ak, "run", str(task), "--bg", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            directory = taskfile.only_run(home)
            wait_for(lambda: fakes["claude"].n == 1)
            second = install.advance()
            tick = home.run(install.ak, "watch", timeout=300)
            self.assertEqual(tick.code, 0, tick.out + tick.err)
            self.assertEqual(install.head(), second)
            release.touch()
            wait_for(lambda: json.loads((directory / "run.json").read_text()).get("state")
                     in ("pass", "fail", "error", "blocked", "exhausted"))
            state = json.loads((directory / "run.json").read_text())
            self.assertTrue(state.get("merged"), (directory / "log.txt").read_text()
                            + str([call["hand_ins"] for fake in fakes.values() for call in fake.runs()]))
            self.assertNotIn("pickup", state)
            for name in ("round-1.code", "round-2.code", "landing.code",
                         "round-1/executor/ak.code", "round-2/executor/ak.code"):
                self.assertEqual((directory / name).read_text().strip(), first, name)
            self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL", "PASS"])
            rig = Rig(home, "gears")
            gh.grant(rig.slug, "WRITE")
            fakes["claude"].behave("work")
            fakes["codex"].behave("pass")
            task = taskfile.write(home, rig.path, "Another retry file")
            done = home.run(install.ak, "run", str(task), timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            newer = next(path for path in taskfile.runs(home) if path != directory)
            for name in ("round-1.code", "landing.code", "round-1/executor/ak.code"):
                self.assertEqual((newer / name).read_text().strip(), second, name)


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
