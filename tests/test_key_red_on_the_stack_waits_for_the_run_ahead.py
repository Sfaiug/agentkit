"""A run red only on top of a run ahead of it in line is fixed once that run has landed.

Two runs on one project pass review.  The first renames the function the project's `api.txt`
names; the second adds `caller.txt`, a call of the name it found there.  The `tests:` suite
fails when the call names no function, so each is green alone and the second is red on top of
the first.  The GitHub here holds the first's `pr merge` until the second has been checked on
top of it; ak then starts no fixer for the second while the first has not merged.  Once it has,
the second is red on the target alone, and its fixer works on a checkout whose main holds the
rename, is re-reviewed on its own file, and the second merges too.  Black-box, as
tests/test_key_landing_train.py is, with its fixtures.
"""

import os
import re
from shlex import quote
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

SUITE = "echo SUITE-SAW $(git log --format=%s | tr '\\n' '|'); test ! -e caller.txt || cmp caller.txt api.txt"
SAW = re.compile(r"^SUITE-SAW (.*)$", re.M)
# The rename writes the new name; the call copies whatever name api.txt holds, and a turn that
# finds its call already there is the fixer, which first notes what the target's main holds.
WORK = ('case $(git branch --show-current) in *rename*) echo hello >api.txt;; '
        '*) [ ! -e caller.txt ] || git show origin/main:api.txt >>{fixed}; cp api.txt caller.txt;; '
        'esac; git add -A; git commit -qm "$(git branch --show-current)"')
# The first's `pr merge` waits for the test's word, and the log says when it ended.
HOLD = """#!/bin/sh
pr=
[ "$1 $2" = "pr merge" ] && for a do case $a in */pull/*|[0-9]|[0-9][0-9]) pr=${{pr:-$a}};; esac
done
if [ -n "$pr" ]; then i=0; while [ ! -e {go} ] && [ $i -lt 1800 ]; do sleep 0.05; i=$((i+1)); done; fi
{gh} "$@"; code=$?
[ -n "$pr" ] && echo "end ${{pr##*/}}" >>{log}
exit $code
"""
DIFF = re.compile(r"^## Diff \(.*?\n```diff\n(.*?)\n```$", re.M | re.S)


class RedOnTheStackWaitsForTheRunAhead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rig = Rig(home, "widgets", files={"AGENTS.md": f"---\ntests: {SUITE}\n---\n# widgets\n",
                                              "api.txt": "greet\n"})
        cls.gh = GitHub(home)
        cls.gh.grant(cls.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        cls.fixed = home.root / "adapters" / "fixed.log"
        cls.fakes = fakeadapter.install(home, codex="pass", claude={
            "sh": WORK.format(fixed=quote(str(cls.fixed))), "final": "## Summary\ndone",
            "hand_in": [["done"]]})
        github = (home.bin / "gh").rename(home.root / "github.sh")
        cls.merges, go = home.root / "merges.log", home.root / "go"
        home.fake("gh", HOLD.format(log=quote(str(cls.merges)), go=quote(str(go)),
                                    gh=quote(str(github))))
        tasks = [str(taskfile.write(home, cls.rig.path, title, done_when=("test -e api.txt",)))
                 for title in ("Rename greet", "Call greet")]
        cls.runs = [home.spawn("run", tasks[0])]
        cls.until(lambda: any("rename" in line for line in cls.saw()))
        cls.runs.append(home.spawn("run", tasks[1]))
        cls.stacked = cls.until(lambda: any("rename" in line and "call" in line
                                            for line in cls.saw()))
        # A fixer that would start before the first lands is given time to; it must not.
        cls.until(lambda: cls.fakes["claude"].n > 2, bound=10)
        cls.early = cls.fixed.exists()
        go.write_text("")
        cls.codes = [cls.ended(proc) for proc in cls.runs]

    @classmethod
    def until(cls, test, bound=240):
        deadline = time.monotonic() + bound
        while not test():
            if time.monotonic() > deadline or all(p.poll() is not None for p in cls.runs):
                return bool(test())
            time.sleep(0.1)
        return True

    @staticmethod
    def ended(proc, bound=300):
        try:
            return proc.wait(timeout=bound)
        except subprocess.TimeoutExpired:
            return None

    @classmethod
    def saw(cls):
        lines = []
        for top, _, names in os.walk(cls.home.path / ".agentkit"):
            for path in (Path(top, name) for name in names):
                try:
                    if path.is_file() and path.stat().st_size < 1 << 20:
                        lines += SAW.findall(path.read_text(errors="replace"))
                except OSError:
                    continue
        return lines

    def outputs(self):
        return "\n".join(self.home.log(f"spawn-{n}.{kind}").read_text()[-3000:]
                         for n in (1, 2) for kind in ("out", "err"))

    def test_the_seconds_fixer_starts_once_the_first_has_merged_on_its_main(self):
        self.assertTrue(self.stacked, self.outputs())
        self.assertFalse(self.early, self.fixed.read_text() if self.early else "")
        self.assertEqual(self.fixed.read_text().split(), ["hello"], self.outputs())

    def test_the_seconds_re_review_reads_its_own_file_alone(self):
        reviews = [Path(call["argv"][3]).read_text() for call in self.fakes["codex"].runs()
                   if "call-greet" in call["argv"][2]]
        self.assertGreater(len(reviews), 1, self.outputs())
        diff = DIFF.search(reviews[-1])
        self.assertIsNotNone(diff, reviews[-1][-3000:])
        self.assertEqual(re.findall(r"^diff --git a/(\S+)", diff[1], re.M), ["caller.txt"])

    def test_both_merge(self):
        self.assertEqual(self.codes, [0, 0], self.outputs())
        self.assertEqual(sorted((pr["title"], pr["state"]) for pr in self.gh.prs()),
                         [("Call greet", "MERGED"), ("Rename greet", "MERGED")])
        self.assertEqual(self.rig.origin("show", "main:caller.txt"), "hello")


if __name__ == "__main__":
    unittest.main()
