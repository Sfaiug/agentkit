"""After a reboot one tick reopens only the seats that owe work, each once per boot, and the
first tick ever only records the boot.

The owner closed by hand, after the 17 Oct reboot, every seat that came back owing nothing (owner
rule, 17 Oct 2026).  A seat owes work when the host went down in the middle of its turn or while
it asked, with its question to the owner standing, or with an open line in its plan; one the
owner closed stays closed whatever it owes, and only a seat whose conversation is its own comes
back.  The tick tells a reboot by the kernel's boot id against the one watch.json holds, so an
install's first tick is none, and it claims each seat before reopening it, so a pass cut off
midway never reopens one twice on that boot.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, each tick in its box, each seat the record tmux lost
(tests/fixtures/akseat.py) with Claude's hooks fired as Claude fires them
(tests/fixtures/hookdrive.py), and what came back is the sessions on ak's tmux server; this test
fails against `/bin/false`.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks

BOOT_FILE = Path("/proc/sys/kernel/random/boot_id")
BOOT = BOOT_FILE.read_text().strip() if BOOT_FILE.is_file() else None
OPEN_LINE = "- [ ] the parser parses · check: `false` · acme · written 2026-10-17 09:00\n"
QUESTION = "Which branch should fix-api land on?"
PERMISSION = {"tool_name": "Bash", "tool_input": {"command": "make deploy"}}
OWN = "notes"   # the owner's own session on ak's tmux server, no seat


def home_for_seats():
    """A Home whose ak runs only Claude and opens no audit seat of its own."""
    home = Home()
    akconfig.write(home, ["opus"])
    # a collection on record from just now: one due would outlive the tick's box
    home.write(".agentkit/state/gc.json", {"started_at": time.time()})
    # The owner's own session keeps ak's tmux server up outside the box: a seat a tick
    # reopened is still there to see once the tick has ended.
    done = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", OWN, "sleep 3600")
    assert done.code == 0, done.err
    return home


def owing_plan(home, name):
    home.write(f".agentkit/state/plan-{name}.md", OPEN_LINE)


def watch_state(home):
    path = home.path / ".agentkit/state/watch.json"
    return json.loads(path.read_text()) if path.is_file() else None


def last_boot(home, **recorded):
    """watch.json as the tick left it on the boot before this one."""
    home.write(".agentkit/state/watch.json",
               {**(watch_state(home) or {}), "boot_id": "before", **recorded})


def sessions(home):
    """The seats on ak's tmux server now, by name."""
    return sorted(set(home.tmux("list-sessions", "-F", "#{session_name}").out.split()) - {OWN})


def close_seats(home):
    """Every seat a tick reopened gone again, as tmux loses it, on the same boot."""
    for name in sessions(home):
        home.tmux("kill-session", "-t", f"={name}")


def reboot_lines(done):
    return [line for line in done.out.splitlines() if " after reboot" in line]


@unittest.skipUnless(REAL_TMUX and BOOT and boxable(), "needs tmux, a kernel boot id and bwrap")
class AfterAReboot(unittest.TestCase):
    OWING = ["asking", "midturn", "planned", "question"]

    @classmethod
    def setUpClass(cls):
        cls.home = home = home_for_seats()
        cls.addClassCleanup(home.close)
        for name in (*cls.OWING, "closed", "idle"):
            Seat(home, name, alive=False)
        # a record from before launches issued ids: nothing says the conversation is its own
        Seat(home, "unowned", alive=False, record={"id_source": None})
        hooks = Hooks(home)
        hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat="midturn")
        for name in ("asking", "closed"):
            hooks.fire("PermissionRequest", PERMISSION, seat=name)
        asked = home.ak("notify", "needs", QUESTION, "--session", "question")
        assert asked.code == 0, asked.err
        for name in ("planned", "closed", "unowned"):
            owing_plan(home, name)
        closed = home.ak("orch", "stop", "closed")
        assert closed.code == 0, closed.err
        last_boot(home)
        cls.before = watch_state(home)
        cls.dry = home.ak("watch", "--dry-run")
        cls.dry_sessions, cls.dry_state = sessions(home), watch_state(home)
        cls.tick = home.tick()
        cls.sessions, cls.state = sessions(home), watch_state(home)
        close_seats(home)
        cls.again = home.tick()
        cls.again_sessions = sessions(home)

    def test_a_dry_run_names_each_seat_it_would_reopen_and_changes_nothing(self):
        self.assertEqual(self.dry.code, 0, self.dry.err)
        self.assertCountEqual(reboot_lines(self.dry),
                              [f"would resume {name} after reboot in {self.home.path}/code/{name}"
                               for name in self.OWING])
        self.assertEqual(self.dry_sessions, [])
        self.assertEqual(self.dry_state, self.before)

    def test_one_tick_reopens_only_the_seats_owing_work(self):
        # not the seat that owes nothing, the one the owner closed, nor the one not its own
        self.assertEqual(self.tick.code, 0, self.tick.err)
        self.assertEqual(self.sessions, self.OWING)
        self.assertCountEqual(reboot_lines(self.tick),
                              [f"resumed {name} after reboot" for name in self.OWING])

    def test_a_seat_reopened_keeps_the_conversation_its_record_names(self):
        for name in self.OWING:
            record = json.loads((self.home.path / f".agentkit/state/session-{name}.json")
                                .read_text())
            self.assertEqual(record.get("conversation"), f"conv-{name}", name)

    def test_the_tick_records_this_boot_and_each_seat_it_tried(self):
        self.assertEqual(self.state["boot_id"], BOOT)
        self.assertEqual(self.state["boot_resume"]["id"], BOOT)
        self.assertCountEqual(self.state["boot_resume"]["attempted"], self.OWING)

    def test_a_seat_comes_back_once_per_boot(self):
        self.assertEqual(self.again.code, 0, self.again.err)
        self.assertEqual(self.again_sessions, [])
        self.assertEqual(reboot_lines(self.again), [])


@unittest.skipUnless(REAL_TMUX and BOOT and boxable(), "needs tmux, a kernel boot id and bwrap")
class OnAFreshInstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = home_for_seats()
        cls.addClassCleanup(home.close)
        for name in ("midturn", "planned"):
            Seat(home, name, alive=False)
        Hooks(home).fire("UserPromptSubmit", {"prompt": "go"}, seat="midturn")
        owing_plan(home, "planned")
        asked = home.ak("notify", "needs", QUESTION, "--session", "planned")
        assert asked.code == 0, asked.err
        (home.path / ".agentkit/state/watch.json").unlink(missing_ok=True)   # never ticked
        cls.dry = home.ak("watch", "--dry-run")
        cls.dry_state = watch_state(home) or {}
        cls.tick = home.tick()
        cls.sessions, cls.state = sessions(home), watch_state(home)

    def test_a_dry_run_records_no_boot(self):
        self.assertEqual(self.dry.code, 0, self.dry.err)
        self.assertEqual(reboot_lines(self.dry), [])
        self.assertNotIn("boot_id", self.dry_state)

    def test_the_first_tick_only_records_the_boot(self):
        self.assertEqual(self.tick.code, 0, self.tick.err)
        self.assertEqual(self.sessions, [])
        self.assertEqual(reboot_lines(self.tick), [])
        self.assertEqual(self.state["boot_id"], BOOT)
        self.assertNotIn("boot_resume", self.state)


@unittest.skipUnless(REAL_TMUX and BOOT and boxable(), "needs tmux, a kernel boot id and bwrap")
class AfterAPassCutOff(unittest.TestCase):
    """watch.json as a pass left it that died after claiming `acme`, or one on the boot before."""

    @classmethod
    def setUpClass(cls):
        home = home_for_seats()
        cls.addClassCleanup(home.close)
        for name in ("acme", "beta"):
            Seat(home, name, alive=False)
            owing_plan(home, name)
        last_boot(home, boot_resume={"id": BOOT, "attempted": ["acme"]})
        cls.cut = home.tick()
        cls.cut_sessions, cls.cut_state = sessions(home), watch_state(home)
        close_seats(home)
        last_boot(home, boot_resume={"id": "before", "attempted": ["acme", "beta"]})
        cls.older = home.tick()
        cls.older_sessions, cls.older_state = sessions(home), watch_state(home)

    def test_a_seat_this_boot_already_tried_is_not_tried_again(self):
        self.assertEqual(self.cut.code, 0, self.cut.err)
        self.assertEqual(self.cut_sessions, ["beta"])
        self.assertEqual(reboot_lines(self.cut), ["resumed beta after reboot"])
        self.assertEqual(self.cut_state["boot_id"], BOOT)
        self.assertEqual(self.cut_state["boot_resume"]["id"], BOOT)
        self.assertCountEqual(self.cut_state["boot_resume"]["attempted"], ["acme", "beta"])

    def test_a_claim_made_on_the_boot_before_counts_for_nothing(self):
        self.assertEqual(self.older.code, 0, self.older.err)
        self.assertEqual(self.older_sessions, ["acme", "beta"])
        self.assertEqual(self.older_state["boot_resume"]["id"], BOOT)
        self.assertCountEqual(self.older_state["boot_resume"]["attempted"], ["acme", "beta"])


if __name__ == "__main__":
    unittest.main()
