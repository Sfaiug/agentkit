"""A project's `setup:` makes the machine ak runs on ready for it, once per machine and version.

`setup:` in a project's AGENTS.md front matter names one executable file of its default branch
(`origin/HEAD`).  The tick runs it in the background, in the project's checkout, once on each
machine (`/etc/machine-id`) for each version of that line and of that file, and on every tick
after a try that failed.  What runs is the file as the default branch records it, whatever the
checkout has checked out or its git and the user's would make of it; a line naming no file of the
commit's own -- an absolute path, a path through a committed link, a link -- runs nothing.
Black-box: `AK_BIN` runs `ak watch` in `home.tick()`'s box with an `/etc/machine-id` of the
test's, on projects from gitrig.py whose setup appends a word to `ran` in its working directory;
judged by `ran` and what `state/setup/<project>.json` says of the last try.
"""

import json
import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home, boxable
from fixtures.gitrig import Rig

SAYS = "#!/bin/sh\necho {} >>ran\n"


@unittest.skipUnless(boxable() and Path("/etc/machine-id").is_file(),
                     "no bwrap able to box a tick here, or no /etc/machine-id to bind over")
class Setups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])     # no audit seat, which would outlive the box
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        cls.machine, cls.rigs, cls.seen, cls.failed = home.root / "machine-id", {}, [], []
        cls.make("plain", "tools/setup", {"tools/setup": SAYS.format("one")})
        cls.make("flaky", "tools/setup", {"tools/setup": SAYS.format("try") + "test -e ok\n"})
        cls.make("missing", "tools/setup", {})
        own = cls.make("own", "tools/my setup", {"tools/my setup": SAYS.format("main")})
        own.git("checkout", "-q", "-b", "draft")
        cls.change(own, {"tools/my setup": SAYS.format("draft")})
        for key, value in (("core.autocrlf", "true"), ("filter.evil.smudge", "sed s/main/evil/")):
            own.git("config", key, value)
        (own.path / ".git/info/attributes").write_text("* filter=evil\n")
        home.write(".config/git/attributes", "* text eol=crlf\n")
        # lines naming no file of the commit's own, each beside a committed executable
        code = home.path / "code"
        cls.named = {"absolute": str(code / "acme-absolute/tools/setup"),
                     "dotdot": "link/../tools/setup", "under": "bin/setup", "linked": "tools/run"}
        links = {"dotdot": {"link": code / "acme-dotdot/tools"}, "under": {"bin": "tools"},
                 "linked": {"tools/run": "setup"}}
        for name, line in cls.named.items():
            cls.make(name, line, {"tools/setup": SAYS.format(name)}, links.get(name, {}))
        cls.tick("a" * 32)
        cls.rigs["plain"].commit({"notes.txt": "another file\n"})
        cls.change(cls.rigs["missing"], {"tools/setup": SAYS.format("ok")}, 0o644)
        cls.tick("a" * 32)
        (cls.rigs["flaky"].path / "ok").touch()
        cls.change(cls.rigs["missing"], {"tools/setup": SAYS.format("ok")})
        cls.tick("b" * 32)
        cls.change(cls.rigs["plain"], {"tools/setup": SAYS.format("two")})
        cls.tick("b" * 32)
        cls.change(cls.rigs["plain"], {"tools/setup": SAYS.format("two")}, 0o644)
        cls.tick("b" * 32)

    @classmethod
    def make(cls, name, line, files, links={}):
        rig = cls.rigs[name] = Rig(cls.home, f"acme-{name}",
                                   files={"AGENTS.md": f"---\nsetup: {line}\n---\n# acme\n"})
        cls.change(rig, files, links=links)
        return rig

    @staticmethod
    def change(rig, files, mode=0o755, links={}):
        for relative, text in files.items():
            path = rig.path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            path.chmod(mode)
        for relative, target in links.items():
            os.symlink(target, rig.path / relative)
        rig.commit({})

    @classmethod
    def tick(cls, machine):
        cls.machine.write_text(f"{machine}\n")
        done = cls.home.tick(box=("--ro-bind", str(cls.machine), "/etc/machine-id"))
        assert done.code == 0, done.out + done.err
        ran = {name: rig.path / "ran" for name, rig in cls.rigs.items()}
        cls.seen.append({name: path.read_text().split() if path.exists() else []
                         for name, path in ran.items()})
        state = cls.home.path / ".agentkit/state/setup"
        cls.failed.append({name: json.loads((state / f"acme-{name}.json").read_text()).get("failed")
                           for name in cls.rigs})

    def runs(self, name):
        return [len(seen[name]) for seen in self.seen]

    def test_it_runs_once_and_again_on_another_machine_a_changed_file_and_one_not_executable(self):
        self.assertEqual(self.seen[-1]["plain"], ["one", "one", "two"])
        self.assertEqual(self.runs("plain"), [1, 1, 2, 3, 3])
        self.assertEqual([failed["plain"] for failed in self.failed[:4]], [None] * 4)
        self.assertRegex(self.failed[4]["plain"][0], "^tools/setup cannot start: ")

    def test_it_runs_the_default_branch_s_file_as_recorded_whatever_the_checkout_holds(self):
        self.assertEqual(self.seen[-1]["own"], ["main", "main"])
        self.assertEqual(self.runs("own"), [1, 1, 2, 2, 2])

    def test_a_failing_setup_runs_each_tick_until_it_passes(self):
        self.assertEqual(self.runs("flaky"), [1, 2, 3, 3, 3])
        self.assertEqual(self.failed[1]["flaky"], ["tools/setup exited 1"])
        self.assertIsNone(self.failed[2]["flaky"])

    def test_a_missing_or_not_executable_file_runs_once_the_default_branch_has_it_executable(self):
        self.assertEqual(self.failed[0]["missing"], ["the default branch holds no tools/setup"])
        self.assertRegex(self.failed[1]["missing"][0], "^tools/setup cannot start: ")
        self.assertEqual(self.runs("missing"), [0, 0, 1, 1, 1])

    def test_a_line_naming_no_file_of_the_commit_s_own_runs_nothing(self):
        for name, line in self.named.items():
            with self.subTest(line):
                self.assertEqual(self.runs(name), [0] * 5)
                self.assertEqual(self.failed[0][name], [f"the default branch holds no {line}"])


if __name__ == "__main__":
    unittest.main()
