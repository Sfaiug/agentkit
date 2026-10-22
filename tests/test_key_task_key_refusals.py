"""A task's front matter holds only lines ak reads: anything else refuses the launch.

`ak run` reads a task file's front matter before it makes anything, so a key it does not know,
the retired `after:`, a line that is no `key: value`, a front matter left open or a round
budget over three each end the launch with exit 2 and one line saying why, and no run or job is
recorded, `--anyway` or not: a mistyped key would otherwise be dropped in silence and the run
would do something nobody asked for.  A `merge:` method ak cannot use is caught as the run
starts, and ends it before any turn or branch.  The retired time keys (`done_when_minutes`,
`turn_hours`, `stall_minutes`) still parse, so older task files run: each is warned once in the
run's log and changes nothing.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py and scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

ACCEPTED = ("after, base, done_when_minutes, files, from, merge, repo, rounds, stall_minutes, "
            "target, turn_hours")
AFTER_GONE = ("ak run: `after:` is gone: tasks launched together are independent pieces; build "
              "work that waits on another piece in your session, in order\n")
RETIRED = ("done_when_minutes", "turn_hours", "stall_minutes")


def project(case):
    """A Home with a project, two models and harnesses that would work if a turn ran."""
    case.home = Home()
    case.addClassCleanup(case.home.close)
    case.rig = Rig(case.home, "widgets")
    akconfig.write(case.home, ["opus", "astra"])
    case.fakes = fakeadapter.install(case.home, claude="work", codex="pass")


def recorded(home):
    """Every entry under HOME/.agentkit/runs and jobs; a directory not made holds none."""
    found = {}
    for name in ("runs", "jobs"):
        where = home.path / ".agentkit" / name
        found[name] = sorted(path.name for path in where.iterdir()) if where.is_dir() else []
    return found


def edited(path, old, new):
    text = path.read_text()
    assert old in text, text
    path.write_text(text.replace(old, new, 1))
    return path


class FrontMatterRefusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project(cls)

    def refused(self, *args):
        """Launch, expect the refusal, and that nothing started; stderr."""
        done = self.home.ak("run", *map(str, args))
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual(done.out, "")
        self.assertEqual(recorded(self.home), {"runs": [], "jobs": []})
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))
        self.assertEqual(self.rig.branches(remote=False), ["main"])
        return done.err

    def unknown(self, task, key):
        return (f"ak run: {task}: unknown front-matter key {key!r}; "
                f"accepted keys: {ACCEPTED}\n")

    def test_the_after_key_is_refused_as_gone_even_with_anyway_or_in_the_background(self):
        task = taskfile.write(self.home, self.rig.path, "Fix api after",
                              front={"after": "other.md"})
        for flags in ((), ("--anyway",), ("--bg",)):
            with self.subTest(flags=flags):
                self.assertEqual(self.refused(task, *flags), AFTER_GONE)

    def test_an_unknown_key_is_refused_naming_it_and_every_key_ak_reads(self):
        cases = (("colour", self.rig.path, {"colour": "red"}, ()),
                 ("colour", None, {"repo": "none", "colour": "blue"}, ("--anyway",)),
                 ("afer", self.rig.path, {"afer": "x"}, ("--bg",)),
                 # spaces around the key and a comment after the value are not part of it
                 ("afer", None, {"repo": "none", "  afer ": "x # a note"}, ("--anyway",)))
        for n, (key, repo, front, flags) in enumerate(cases, 1):
            with self.subTest(front=front, flags=flags):
                task = taskfile.write(self.home, repo, f"Fix beta {n}", front=front)
                self.assertEqual(self.refused(task, *flags), self.unknown(task, key))

    def test_an_unknown_key_in_one_task_of_a_job_refuses_the_whole_job(self):
        good = taskfile.write(self.home, self.rig.path, "Fix gamma")
        bad = taskfile.write(self.home, self.rig.path, "Fix delta", front={"colour": "red"})
        for args in ((good, bad), (good, bad, "--bg"), (bad, good, "--parallel", "2")):
            with self.subTest(args=args[2:]):
                self.assertEqual(self.refused(*args), self.unknown(bad, "colour"))

    def test_front_matter_left_open_a_line_with_no_key_or_rounds_over_three_is_refused(self):
        def task(name, **kw):
            return taskfile.write(self.home, self.rig.path, f"Fix {name}", **kw)
        opened = edited(task("open"), "\n---\n#", "\n#")
        bogus = edited(task("bogus"), "\n---\n#", "\nbogus line\n---\n#")
        cases = {"open": (opened, (str(opened), "closing ---")),
                 "bogus": (bogus, (str(bogus), "'bogus line'")),
                 "rounds": (task("rounds", front={"rounds": 4}), ("rounds 4", "3 rounds"))}
        for name, (path, why) in cases.items():
            with self.subTest(name):
                err = self.refused(path, "--bg")
                self.assertTrue(err.startswith("ak run: "), err)
                self.assertEqual(len(err.splitlines()), 1, err)
                for words in why:
                    self.assertIn(words, err)


class BadMergeMethod(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project(cls)

    def test_a_merge_method_ak_cannot_use_ends_the_run_before_any_turn_or_branch(self):
        for method, flags in (("fast", ("--no-merge",)), ("squish", ())):
            with self.subTest(method=method, flags=flags):
                title = f"Fix api {method}"
                task = taskfile.write(self.home, self.rig.path, title, front={"merge": method})
                done = self.home.ak("run", str(task), *flags, timeout=300)
                self.assertEqual(done.code, 2, done.out + done.err)
                # A merging foreground run follows the run's own process and prints what it
                # says, so there the refusal reaches the terminal on either stream.
                said = done.err if flags else done.out + done.err
                why = f": merge must be one of squash, merge, rebase (got {method!r})"
                self.assertTrue([line for line in said.splitlines()
                                 if line.startswith("ak run: ") and line.endswith(why)], said)
                for run in taskfile.runs(self.home):
                    if run.name.endswith(taskfile.slug(title)):
                        state = json.loads((run / "run.json").read_text())
                        self.assertEqual(state["state"], "error")
                        self.assertIn(f"(got {method!r})", state["error"])
                self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))
                self.assertEqual(self.rig.branches(remote=False), ["main"])
                self.assertEqual(self.rig.branches(), ["main"])
                self.assertEqual(self.home.calls("gh"), [])


class RetiredTimeKeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project(cls)
        old = taskfile.write(cls.home, cls.rig.path, "Keep old keys",
                             front={"done_when_minutes": 30, "turn_hours": 2,
                                    "stall_minutes": 1})
        plain = taskfile.write(cls.home, cls.rig.path, "Keep plain")
        cls.done = {}
        for task in (old, plain):
            cls.done[task.stem] = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.runs = {stem: next(run for run in taskfile.runs(cls.home) if run.name.endswith(stem))
                    for stem in cls.done}

    def state(self, stem):
        return json.loads((self.runs[stem] / "run.json").read_text())

    def log(self, stem):
        return (self.runs[stem] / "log.txt").read_text()

    def test_a_task_with_the_retired_time_keys_still_runs_and_passes(self):
        done = self.done["keep-old-keys"]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((self.state("keep-old-keys")["state"],
                          self.state("keep-old-keys")["verdict"]), ("pass", "PASS"))

    def test_each_retired_key_is_warned_once_in_the_runs_log(self):
        for key in RETIRED:
            line = f"ignoring {key}: the loop watches for silence"
            with self.subTest(key):
                self.assertEqual(self.log("keep-old-keys").count(line), 1)
                self.assertEqual(self.log("keep-plain").count(line), 0)

    def test_the_retired_keys_change_none_of_the_runs_limits(self):
        self.assertEqual(self.done["keep-plain"].code, 0, self.done["keep-plain"].err)
        for limit in ("silence_minutes", "ceiling_hours"):
            with self.subTest(limit):
                self.assertEqual(self.state("keep-old-keys").get(limit),
                                 self.state("keep-plain").get(limit))
                self.assertIsNotNone(self.state("keep-plain").get(limit))


if __name__ == "__main__":
    unittest.main()
