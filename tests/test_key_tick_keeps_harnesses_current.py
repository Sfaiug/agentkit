"""The tick from ak's own install keeps each harness on its latest release; no other tick does.

A harness the host has is asked its `[update] latest` at most once an hour, and one behind it is
upgraded in the background, one at a time.  A red puts the harness back and says so, and that
release starts again once a day has passed since its start, a newer one at once.  A tick from any
other checkout, a test's above all, neither asks nor upgrades.  Black-box: every tick is
`AK_BIN watch` itself, through tests/fixtures/akbin.py, in an offline box where HOME/agentkit is
the checkout the program runs from, a copy of it as it stands mounted over it, or for another
checkout's tick that copy beside it; claude and codex are fakes keeping their installed release
and their channel's in files, npm answers for both, and tests/fixtures/akgates.py stands in for
the gates; an hour or a day goes by as the record of each ask and start is set back.  This test
fails against `/bin/false`.
"""

from collections import Counter
import functools
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, LOG, Home, boxable
from fixtures.akgates import Gates

ASK_EVERY = 60 * 60
RETRY_AFTER = 24 * 60 * 60
SLACK = 5 * 60      # more than the ticks between an ask and the look at it ever take
# `install latest` takes the channel's release, but not while `hold` is there.
CLAUDE = """case "$1 $2" in
  "--version "*) cat {root}/claude ;;
  "install latest") while [ -f {root}/hold ]; do sleep 0.1; done
                    echo "$(cat {root}/claude.latest) (Claude Code)" >{root}/claude ;;
  "install "*) echo "$2 (Claude Code)" >{root}/claude ;;
  *) exit 1 ;;
esac
"""
CODEX = """case "$1" in
  --version) echo "codex-cli $(cat {root}/codex)" ;;
  *) exit 1 ;;
esac
"""
NPM = """case "$1 $2 $3" in
  "view @anthropic-ai/claude-code version") cat {root}/claude.latest ;;
  "view @openai/codex version") cat {root}/codex.latest ;;
  "i -g @openai/codex@latest") cp {root}/codex.latest {root}/codex ;;
  "i -g @openai/codex@"*) echo "${{3#@openai/codex@}}" >{root}/codex ;;
  *) exit 1 ;;
esac
"""
PACKAGES = {"@anthropic-ai/claude-code": "claude", "@openai/codex": "codex"}


def starts(name, old, new):
    return f"{name} {old} is behind {new}: upgrading it in the background"


def box(home, *words):
    """bwrap's words for `home.box()`'s box, offline, as nothing here may reach a network, and
    with `words` last, so a mount they make lands over that box's own."""
    return [*home.box()[:-1], "--unshare-net", *words, "--"]


@functools.cache
def program():
    """The file `AK_BIN watch` runs, through any wrapper -- the word before `watch` on the command
    line of the first process to call tmux -- and the checkout it runs from, as ak takes it: the
    nearest folder above holding .git, else the one above its bin/."""
    with Home() as home:
        seen = home.root / "seen"
        home.fake("tmux", "#!/bin/sh\n[ -e {0} ] || cp /proc/$PPID/cmdline {0}\nexit 1\n".format(
            shlex.quote(str(seen))))
        home.run(*box(home), AK, "watch")
        assert seen.exists(), "the tick called no tmux"
        words = seen.read_bytes().split(b"\0")
        ran = (home.path / os.fsdecode(words[words.index(b"watch") - 1])).resolve()
    return ran, next((folder for folder in ran.parents if (folder / ".git").exists()),
                     ran.parents[1])


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class KeepsHarnessesCurrent(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        ran, self.checkout = program()
        # each tick's box puts a copy in the checkout's place, which would hide a Home inside it
        self.assertFalse(home.root.is_relative_to(self.checkout),
                         f"TMPDIR is inside the program's checkout, {self.checkout}")
        # The install: the program's checkout as it stands -- what git tracks or would add, a
        # launcher and its symlinks among them -- and the program and `AK_BIN` as built, resolved
        # so no `..` names a place outside the copy; on main as its origin has it.
        self.root = root = home.root
        self.copy = copy = root / "install"
        listed = home.run("git", "-C", str(self.checkout), "ls-files", "-z", "--cached",
                          "--others", "--exclude-standard")
        built = [str(path.relative_to(self.checkout)) for path in (ran, Path(AK).resolve())
                 if path.is_relative_to(self.checkout)]
        for name in {*(listed.out.split("\0") if listed.code == 0 else ()), *built} - {""}:
            source = self.checkout / name
            if source.is_file() or source.is_symlink():
                (copy / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, copy / name, follow_symlinks=False)
        origin = str(root / "origin.git")
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "ak"],
                     ["init", "-q", "--bare", origin], ["remote", "add", "origin", origin],
                     ["push", "-q", "origin", "main"]):
            done = home.run("git", "-C", str(copy), *args)
            self.assertEqual(done.code, 0, done.err)
        # HOME/agentkit names a path only a box's own /tmp holds: on the host it leads nowhere.
        self.link = f"/tmp/{root.name}-agentkit"
        (home.path / "agentkit").symlink_to(self.link)
        python = shlex.quote(sys.executable)
        for name, script in (("claude", CLAUDE), ("codex", CODEX), ("npm", NPM)):
            home.fake(name, LOG.format(python=python, log=shlex.quote(str(home.log(name))))
                      + script.format(root=shlex.quote(str(root))))
        self.write(claude="2.1.0 (Claude Code)", codex="0.1.0")
        self.write(**{"claude.latest": "2.1.0", "codex.latest": "0.1.0"})
        self.gates = Gates(home)

    def write(self, **files):
        for name, text in files.items():
            (self.root / name).write_text(text + "\n")

    def installed(self, name):
        return (self.root / name).read_text().strip()

    def asks(self):
        """How often each harness's latest release was asked."""
        return Counter(PACKAGES[call[1]] for call in self.home.calls("npm") if call[0] == "view")

    def installs(self):
        """Every install of a harness begun, oldest first within each."""
        return ([shlex.join(["claude", *call]) for call in self.home.calls("claude")
                 if call[0] == "install"]
                + [shlex.join(["npm", *call]) for call in self.home.calls("npm") if call[0] == "i"])

    def passes(self, seconds):
        """`seconds` go by for the record of each harness's last ask and start."""
        path = self.home.path / ".agentkit" / "state" / "harness-latest.json"
        path.write_text(json.dumps({name: {key: value - seconds if isinstance(value, (int, float))
                                           else value for key, value in entry.items()}
                                    for name, entry in json.loads(path.read_text()).items()}))

    def tick(self, own=True):
        """One `AK_BIN watch`: what it said.  In its box HOME/agentkit leads to the program's own
        checkout, the copy mounted over it, or else to the copy beside the checkout it runs from.
        What it leaves running stays in that box."""
        words = (("--bind", self.copy, self.checkout, "--symlink", self.checkout, self.link)
                 if own else ("--symlink", self.copy, self.link))
        done = self.home.run(*box(self.home, *map(str, words)), AK, "watch")
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out.splitlines()

    def told(self, name):
        """Ticks until one tells how `name`'s background upgrade ended: what they all said."""
        said, deadline = [], time.monotonic() + 120
        while not any(f"background upgrade of {name}" in line for line in said):
            self.assertLess(time.monotonic(), deadline, f"{name}'s upgrade was never told")
            said += self.tick()
        return said

    def red(self):
        """claude 2.2.0 started, failed by its gate and put back: what the ticks said."""
        self.write(**{"claude.latest": "2.2.0"})
        self.gates.exit("live", 1)
        said = self.tick()
        self.assertIn(starts("claude", "2.1.0", "2.2.0"), said)
        said += self.told("claude")
        self.gates.reset()
        return said

    def test_a_tick_asks_each_latest_once_an_hour(self):
        self.tick()
        self.assertEqual(self.asks(), {"claude": 1, "codex": 1})
        self.passes(ASK_EVERY - SLACK)
        self.tick()
        self.assertEqual(self.asks(), {"claude": 1, "codex": 1})
        self.passes(SLACK)
        self.tick()
        self.assertEqual(self.asks(), {"claude": 2, "codex": 2})
        self.assertEqual(self.installs(), [])

    def test_one_behind_is_upgraded_in_the_background_one_at_a_time(self):
        self.write(hold="", **{"claude.latest": "2.2.0", "codex.latest": "0.2.0"})
        said = self.tick()
        self.assertIn(starts("claude", "2.1.0", "2.2.0"), said)
        self.assertNotIn(starts("codex", "0.1.0", "0.2.0"), said)
        deadline = time.monotonic() + 120
        while not self.installs():
            self.assertLess(time.monotonic(), deadline, "claude's upgrade never began")
            time.sleep(0.1)
        # the tick that started it has ended, and claude's install has not
        self.assertNotIn(starts("codex", "0.1.0", "0.2.0"), self.tick())
        self.assertEqual(self.installs(), ["claude install latest"])
        self.assertEqual(self.installed("claude"), "2.1.0 (Claude Code)")
        (self.root / "hold").unlink()
        said = self.told("claude") + self.told("codex")
        self.assertIn(starts("codex", "0.1.0", "0.2.0"), said)
        self.assertEqual(self.installs(), ["claude install latest",
                                           "npm i -g @openai/codex@latest"])
        self.assertEqual((self.installed("claude"), self.installed("codex")),
                         ("2.2.0 (Claude Code)", "0.2.0"))
        self.assertEqual(self.asks(), {"claude": 1, "codex": 1})

    def test_a_red_is_put_back_and_said(self):
        said = self.red()
        self.assertIn("WARN the background upgrade of claude failed:", said)
        self.assertIn("  update: claude: reverted, back on 2.1.0 (Claude Code)", said)
        self.assertEqual(self.installed("claude"), "2.1.0 (Claude Code)")
        self.assertEqual(self.installs(), ["claude install latest", "claude install 2.1.0"])

    def test_a_red_release_starts_again_once_a_day_has_passed_since_its_start(self):
        self.red()
        self.passes(RETRY_AFTER - ASK_EVERY)
        self.tick()
        self.assertEqual(self.asks()["claude"], 2)
        self.assertEqual(len(self.installs()), 2)
        self.passes(ASK_EVERY)
        self.assertIn(starts("claude", "2.1.0", "2.2.0"), self.tick())
        self.told("claude")
        self.assertEqual(self.installed("claude"), "2.2.0 (Claude Code)")

    def test_a_newer_release_starts_at_once_after_a_red(self):
        self.red()
        self.write(**{"claude.latest": "2.3.0"})
        self.passes(ASK_EVERY)
        self.assertIn(starts("claude", "2.1.0", "2.3.0"), self.tick())
        self.told("claude")
        self.assertEqual(self.installed("claude"), "2.3.0 (Claude Code)")

    def test_a_tick_from_any_other_checkout_neither_asks_nor_upgrades(self):
        self.write(**{"claude.latest": "2.2.0", "codex.latest": "0.2.0"})
        self.tick(own=False)
        self.assertEqual((self.asks(), self.installs()), (Counter(), []))
        # the install's own tick, on the same home, does both
        self.assertIn(starts("claude", "2.1.0", "2.2.0"), self.tick())
        self.assertEqual(self.asks(), {"claude": 1})


if __name__ == "__main__":
    unittest.main()
