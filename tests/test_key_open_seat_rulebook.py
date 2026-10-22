"""A seat opened from a terminal runs on its rulebook: ak's rules, the host's, then its project's.

A seat's rules have three homes, each handed to it whole (owner rules): orchestrator.md, the
host's ~/.agentkit/rules.md, and the project's AGENTS.md as merged on its default branch, never as
one checkout, branch or edit holds it, front matter removed.  ak writes the rulebook before the
seat's harness is asked for its command line and names the file to its adapter in
$AGENTKIT_RULEBOOK; host rules that cannot be read refuse the launch, so no seat works to rules
nobody chose.  The harness runs in the seat's tmux session as that seat, in the directory it was
opened from, with ak's guard shims first on its PATH.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, on an adapter of this test's own that keeps what it
is told, for projects of tests/fixtures/gitrig.py; this test fails against `/bin/false`.
"""

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.gitrig import Rig

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ORCHESTRATOR = (Path(__file__).resolve().parents[1] / "orchestrator.md").read_text()
HOST_RULE = "Acme host rule: answer in haiku."
HEADING = "# The project's AGENTS.md"
FRONT = "---\nusers: none\ntests: true\nhealth: true\n---\n"
SHIMS = ("git", "gh", "tmux", "scp", "rsync", "sftp")
# The echo fixture's verbs, a conversation id refused as echo refuses one; but `interactive`
# keeps each asking and the rulebook it named, and its seat what it started in, then is a shell.
HARNESS = """#!{python}
import json, os, shlex, sys
if sys.argv[1:2] != ["interactive"]:
    os.execv({echo!r}, [{echo!r}, *sys.argv[1:]])
book = os.environ.get("AGENTKIT_RULEBOOK")
with open({root!r} + "/told.jsonl", "a") as told:
    told.write(json.dumps({{"seat": os.environ.get("AGENTKIT_SESSION"), "argv": sys.argv[1:],
                           "rulebook": book, "text": book and open(book).read()}}) + "\\n")
if len(sys.argv) > 4:
    sys.exit(3)
SEAT = ("import json, os; json.dump({{'cwd': os.getcwd(), 'env': dict(os.environ)}}, "
        "open({root!r} + '/seat-' + os.environ.get('AGENTKIT_SESSION', '') + '.json', 'w')); "
        "os.execv('/bin/sh', ['sh'])")
print(shlex.join([sys.executable, "-c", SEAT]))
"""


def echo_home():
    """A Home whose two models, `one` and `two`, run on the logging echo harness."""
    home = Home()
    adapters = home.root / "adapters"
    adapters.mkdir()
    shutil.copy(FIXTURES / "adapters" / "echo.toml", adapters / "echo.toml")
    script = adapters / "echo.sh"
    script.write_text(HARNESS.format(python=sys.executable, root=str(home.root),
                                     echo=str(FIXTURES / "adapters" / "echo.sh")))
    script.chmod(0o755)
    home.env["AGENTKIT_ADAPTER_DIR"] = str(adapters)
    akconfig.write(home, {"one": {"harness": "echo", "model": "echo-1", "provider": "test"},
                          "two": {"harness": "echo", "model": "echo-2", "provider": "test"}})
    return home


class Opening:
    def open(self, name, cwd):
        """`ak orch NAME` typed in a terminal there; its exit and what it printed."""
        return self.home.ak("orch", name, "--model", "two", "--workers", "one", tty=True,
                            cwd=cwd)

    def opened(self, name, cwd):
        done = self.open(name, cwd)
        self.assertEqual(done.code, 0, done.err)

    def state(self, name):
        return self.home.path / ".agentkit" / "state" / name

    def rulebook(self, seat):
        return self.state(f"rulebook-{seat}.md").read_text()

    def record(self, seat):
        return json.loads(self.state(f"session-{seat}.json").read_text())

    def told(self, seat):
        lines = (self.home.root / "told.jsonl").read_text().splitlines()
        return [ask for ask in map(json.loads, lines) if ask["seat"] == seat]

    def harness(self, seat, bound=30):
        """What the seat's harness found when it started: it starts a moment after the launch."""
        path, deadline = self.home.root / f"seat-{seat}.json", time.monotonic() + bound
        while True:
            try:
                return json.loads(path.read_text())
            except (FileNotFoundError, ValueError):
                if time.monotonic() > deadline:
                    raise AssertionError(f"no harness started as seat {seat}") from None
                time.sleep(0.05)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatRulebook(Opening, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = echo_home()
        cls.addClassCleanup(cls.home.close)
        cls.home.write(".agentkit/rules.md", HOST_RULE + "\n")

    def project(self, name, body):
        """A project whose clone has not fetched since its first push: no origin/HEAD yet."""
        return Rig(self.home, name, files={"AGENTS.md": FRONT + body + "\n"})

    def merge_elsewhere(self, rig, body):
        """AGENTS.md changed on the origin's main by another clone, unseen by the project's."""
        other = self.home.root / "elsewhere" / rig.name
        self.git("clone", "-q", str(rig.bare), str(other))
        (other / "AGENTS.md").write_text(FRONT + body + "\n")
        for args in (("add", "-A"), ("commit", "-qm", "rules"), ("push", "-q", "origin", "main")):
            self.git("-C", str(other), *args)

    def git(self, *args):
        done = self.home.run("git", *args)
        self.assertEqual(done.code, 0, done.err)

    def test_a_seat_opened_from_a_terminal_runs_its_harness_as_that_seat_behind_the_guards(self):
        cwd = self.home.path / "code" / "acme"
        cwd.mkdir(parents=True)
        self.opened("echo-seat", cwd)
        self.assertEqual(self.home.tmux("has-session", "-t", "=echo-seat").code, 0)
        self.assertEqual(self.home.tmux("show-options", "-v", "-t", "=echo-seat:",
                                        "@ak_orch").out, "1\n")
        record = self.record("echo-seat")
        self.assertEqual((record["orchestrator"], record["workers"], record["cwd"]),
                         ("two", ["one"], str(cwd)))
        self.assertTrue(self.told("echo-seat"))
        for ask in self.told("echo-seat"):
            self.assertEqual(ask["argv"][1:3], ["echo-2", "high"])
        started = self.harness("echo-seat")
        self.assertEqual(started["cwd"], str(cwd))
        self.assertEqual(started["env"]["AGENTKIT_SESSION"], "echo-seat")
        shims = self.home.path / ".agentkit" / "bin"
        self.assertEqual(started["env"]["PATH"].split(os.pathsep)[0], str(shims))
        for shim in SHIMS:
            self.assertTrue(os.access(shims / shim, os.X_OK), shim)

    def test_a_seat_with_no_project_rules_is_handed_ak_s_rules_then_the_host_s_alone(self):
        nowhere = self.home.path / "code" / "nowhere"
        nowhere.mkdir(parents=True)
        unruled = Rig(self.home, "unruled")
        linked = Rig(self.home, "linked", files={"docs/rules.md": "Always FROBNICATE.\n"})
        (linked.path / "AGENTS.md").symlink_to("docs/rules.md")
        linked.commit({}, "link the rules")
        for seat, cwd in (("nowhere", nowhere), ("unruled", unruled.path),
                          ("linked", linked.path)):
            with self.subTest(seat):
                self.opened(seat, cwd)
                book, path = self.rulebook(seat), str(self.state(f"rulebook-{seat}.md"))
                self.assertTrue(book.startswith(ORCHESTRATOR.rstrip()))
                self.assertEqual(book.replace(ORCHESTRATOR.rstrip(), "", 1).strip(), HOST_RULE)
                self.assertTrue(self.told(seat))
                for ask in self.told(seat):
                    self.assertEqual((ask["rulebook"], ask["text"]), (path, book))
                self.assertEqual(self.record(seat)["rulebook_sha"],
                                 hashlib.sha256(book.encode()).hexdigest())

    def test_a_seat_in_a_project_is_handed_its_agents_md_as_merged_on_the_default_branch(self):
        rig = self.project("proj", "Always FROBNICATE.")
        rig.git("checkout", "-q", "-b", "fix-api")
        rig.commit({"AGENTS.md": FRONT + "Never FROBNICATE on a branch.\n"}, push=False)
        (rig.path / "AGENTS.md").write_text(FRONT + "Never FROBNICATE in the tree.\n")
        self.opened("demo", rig.path)
        book = self.rulebook("demo")
        self.assertTrue(book.startswith(ORCHESTRATOR.rstrip()))
        lines = book.splitlines()
        self.assertLess(lines.index(HOST_RULE), lines.index(HEADING))
        self.assertLess(lines.index(HEADING), lines.index("Always FROBNICATE."))
        self.assertNotIn("users: none", lines)
        self.assertNotIn("Never FROBNICATE", book)
        self.assertEqual(self.record("demo")["repo"], str(rig.path))

    def test_a_project_never_fetched_is_fetched_first_and_one_fetched_is_read_as_it_was(self):
        fresh = self.project("beta", "Always FROBNICATE.")
        fetched = self.project("gamma", "Always FROBNICATE.")
        fetched.git("remote", "set-head", "origin", "--auto")
        for rig in (fresh, fetched):
            self.merge_elsewhere(rig, "Always POLISH.")
        for seat, rig, now, was in (("beta", fresh, "Always POLISH.", "Always FROBNICATE."),
                                    ("gamma", fetched, "Always FROBNICATE.", "Always POLISH.")):
            with self.subTest(seat):
                self.opened(seat, rig.path)
                lines = self.rulebook(seat).splitlines()
                self.assertIn(now, lines)
                self.assertNotIn(was, lines)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class HostRules(Opening, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = echo_home()
        cls.addClassCleanup(cls.home.close)

    def test_a_host_with_no_rules_of_its_own_hands_ak_s_rules_alone(self):
        self.opened("alone", self.home.path)
        self.assertEqual(self.rulebook("alone").rstrip(), ORCHESTRATOR.rstrip())

    def test_host_rules_that_cannot_be_read_refuse_the_launch(self):
        rules = self.home.path / ".agentkit" / "rules.md"
        rules.mkdir()
        try:
            done = self.open("refused", self.home.path)
        finally:
            rules.rmdir()
        self.assertNotEqual(done.code, 0, done.out)
        self.assertIn("rules.md", done.err)
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=refused").code, 0)
        self.assertFalse(self.state("session-refused.json").exists())
        self.assertFalse(self.state("rulebook-refused.md").exists())


if __name__ == "__main__":
    unittest.main()
