"""A change of looks alone lands on its quick checks.

A member of a landing line whose change against its target names only raster images, fonts
or prose, AGENTS.md never one of them, is given its verdict to land by the line's
next pass with no whole run of the suite, ahead of members waiting for theirs, where the target
declares both `health:` and `deployed:`, so ak puts back a release whose health breaks, and the
project has a time record of its suite.  Its
merge ends with `Looks-Alone-Tree: <tree>`.  Elsewhere, and for any other change, a member waits
as any does, and what an image breaks the next whole run finds red on the target's tip.

Black-box: the program `AK_BIN` names, on a busy host (AK_HOST_READINGS) where a whole suite
measured at 40 minutes waits for company, checks a landing line from outside through
tests/fixtures/akline.py; the two runs that deliver are scripted by fakeadapter.py and merged
by fakegh.py's GitHub.  The Home here drops the test suites' `AK_MAX_RUNS=0`, which lifts every
host gate.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akline import SUITE, Line
from fixtures.fakegh import GitHub

BUSY = {"cpus": 4, "load": 4, "free_mb": 16000}     # no processor idle
IDLE = {"cpus": 4, "load": 0, "free_mb": 16000}
RULES = f"---\ntests: {SUITE}\nhealth: true\ndeployed: true\n---\n# acme\n"
IMAGE = {"logo.png": "blink\n"}
TIMES = {"t/ok.sh": 1}


def record(directory):
    return json.loads((directory / "run.json").read_text())


class AChangeOfLooksAloneLandsOnItsQuickChecks(unittest.TestCase):
    def line(self, rules=RULES, times=TIMES, **files):
        line = Line({"AGENTS.md": rules, "t/ok.sh": "true\n", **files})
        self.addCleanup(line.close)
        line.home.env.pop("AK_MAX_RUNS")
        line.home.env["AK_HOST_READINGS"] = json.dumps(BUSY)
        line.measured(40 * 60)
        if times is not None:
            line.rig.git("config", "ak.repository", "0123456789ab")
            line.home.write(".agentkit/state/test-times-0123456789ab.json", times)
        return line

    def join(self, line, files):
        """Park the line's next member, joined now, its branch adding `files`."""
        line.member(files)
        state = record(line.members[-1])
        state["waiting_on"]["joined"] = time.time()
        (line.members[-1] / "run.json").write_text(json.dumps(state))

    def land(self, line, readings=BUSY):
        done = line.home.ak("run", "--lander", line.line, timeout=600,
                            env={"AK_HOST_READINGS": json.dumps(readings)})
        self.assertEqual(done.code, 0, done.out + done.err)

    def checked(self, line):
        """How many whole runs of the suite, and which members got a verdict to land."""
        return line.whole(), ["land" in line.verdict(n) for n in range(1, len(line.members) + 1)]

    def test_an_image_lands_with_no_whole_run_while_code_ahead_of_it_waits(self):
        line = self.line()
        home, runs = line.home, line.home.path / ".agentkit" / "runs"
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])

        def work(path):
            return {**fakeadapter.WORK, "write": {path: "x\n"}, "commit": f"add {path}"}

        def run(title):
            return next((record(directory) for directory in runs.glob(f"*-{taskfile.slug(title)}")
                         if (directory / "run.json").is_file()), {})

        worker = fakeadapter.install(home, claude=work("app.py"), codex="pass")["claude"]
        home.spawn("run", str(taskfile.write(home, line.rig.path, "Add the app",
                                             done_when=("test -f app.py",))))
        deadline = time.monotonic() + 300
        while "line" not in (run("Add the app").get("waiting_on") or {}):
            self.assertLess(time.monotonic(), deadline, "the code's run never joined the line")
            time.sleep(0.2)
        worker.behave(work("logo.png"))
        done = home.ak("run", str(taskfile.write(home, line.rig.path, "Draw the logo",
                                                 done_when=("test -f logo.png",))), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        code, looks = run("Add the app"), run("Draw the logo")
        self.assertTrue(looks.get("merged"), looks)
        self.assertEqual(line.whole(), 0, line.runs())
        self.assertFalse({"land", "fix"} & code["waiting_on"].keys(), code)
        tree = line.rig.origin("rev-parse", "main^{tree}")
        self.assertTrue(line.rig.origin("log", "-1", "--format=%B", "main").rstrip().endswith(
            f"\n\nLooks-Alone-Tree: {tree}"))

    def test_where_the_target_declares_no_deployed_it_waits_like_any(self):
        line = self.line(RULES.replace("deployed: true\n", ""))
        self.join(line, IMAGE)
        self.land(line)
        self.assertEqual(self.checked(line), (0, [False]), line.runs())

    def test_behind_a_delivery_that_drops_deployed_it_waits_like_any(self):
        line = self.line()
        self.join(line, {"AGENTS.md": RULES.replace("deployed: true\n", "")})
        self.land(line, IDLE)
        line.measured(40 * 60)      # not the seconds that check took
        self.join(line, IMAGE)
        self.land(line)
        self.assertEqual(self.checked(line), (1, [True, False]), line.runs())

    def test_an_image_committed_in_a_clone_of_its_own_lands_as_any(self):
        line = self.line()
        self.join(line, {"app.js": "x\n"})
        self.join(line, IMAGE)
        clone = line.home.path / "code" / "acme-copy"

        def git(*args):
            done = line.home.run("git", *args)
            self.assertEqual(done.code, 0, done.err)
            return done.out.strip()

        git("clone", "-q", str(line.rig.bare), str(clone))
        (clone / "logo.png").write_text(IMAGE["logo.png"])
        git("-C", str(clone), "add", ".")
        git("-C", str(clone), "commit", "-qm", "draw")
        head = git("-C", str(clone), "rev-parse", "HEAD")
        state = record(line.members[1])
        state.update(repo=str(clone), worktree=str(clone))
        state["review"].update(head_sha=head, passed_head_sha=head,
                               tree_sha=git("-C", str(clone), "rev-parse", "HEAD^{tree}"))
        (line.members[1] / "run.json").write_text(json.dumps(state))
        self.land(line)
        self.assertEqual(self.checked(line), (0, [False, True]), line.runs())

    def test_an_image_beside_a_script_waits(self):
        line = self.line()
        self.join(line, {**IMAGE, "app.js": "x\n"})
        self.join(line, IMAGE)
        self.land(line)
        self.assertEqual(self.checked(line), (0, [False, True]), line.runs())

    def test_agents_md_waits(self):
        line = self.line()
        self.join(line, {"AGENTS.md": RULES + "A shop.\n"})
        self.join(line, IMAGE)
        self.land(line)
        self.assertEqual(self.checked(line), (0, [False, True]), line.runs())

    def test_an_image_that_breaks_a_test_is_found_red_at_the_tip_by_the_next_whole_run(self):
        line = self.line(**{"t/logo.sh": "! grep -q blink logo.png\n"})
        self.join(line, {"app.py": "x\n"})
        self.join(line, IMAGE)
        self.land(line, IDLE)
        # the code waits for the image to be on the target, which the next run stands on
        self.assertEqual(self.checked(line), (0, [False, True]), line.runs())
        # delivered as its run would: its change on the target, its record merged
        line.rig.commit(IMAGE, "draw")
        (line.members[1] / "run.json").write_text(json.dumps(
            {**record(line.members[1]), "state": "pass", "merged": True}))
        self.land(line, IDLE)
        self.assertEqual(line.whole(), 1, line.runs())
        green = json.loads((line.members[0].parent / line.line).with_suffix(".green").read_text())
        red = green["red"][line.rig.origin("rev-parse", "main^{tree}")]
        self.assertEqual((red["probe"]["sha"], red["tests"]), (line.rig.head(), ["logo.sh"]))
        self.assertNotIn("fix", line.verdict(1))


if __name__ == "__main__":
    unittest.main()
