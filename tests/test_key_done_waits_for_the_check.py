"""A seat whose plan has every line done owes a done check of its work against what its owner
said, `ak orch check`'s, which `ak plan` makes: until one finds no gap the seat does not read
done and its stop goes back, and one that does counts until the owner says more.

The owner asks for a retry button and a receipt email; the plan holds the button alone.  The
first check names the email, quoting the owner; once the owner drops it, the next finds no gap.
A check that could not be made counts for nothing, nor does one passed before another that ended
later on a gap, under whichever name the seat went by meanwhile; and a record ak cannot read,
whichever harness keeps it, is no owner who said nothing.  `[done_check] on = false` leaves done
as it was.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, on a Claude seat of tests/fixtures/akseat.py whose
transcript the test writes, with a fake harness of fakeadapter.py for the model, and the hooks
beside that program fired as tests/test_key_live_work_plan_line.py fires them.
"""

import json
import re
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import ROOT

CONVERSATION = "7e1c9a42-5d3b-4f80-a6e2-1b9d4c7f0a53"
FIRST = "Add a retry button to the upload page."
SECOND = "Also email me a receipt after every upload."
DROP = "Forget the receipt email; the retry button is enough."
PLANNED = "The upload page has a retry button"
DONE = "acme  done"
GAP = {"sh": f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- {shlex.quote(SECOND)} . | "
             f"head -n 1):1\" 'no receipt email' 'the owner asked for it' "
             f"--quote {shlex.quote(SECOND)}",
       "final": "Checked.", "hand_in": [["done"]]}
NONE = {"final": "Checked.", "hand_in": [["done"]]}
TOKEN = "a" * 32    # an OpenCode or Codex seat's launch receipt


def codex_seat(home):
    """(launch receipt, transcript) of a Codex seat `acme` whose thread the owner asked of, as
    Codex's SessionStart hook and its rollout write them."""
    cwd = str(home.path / "code" / "acme")
    rollout = home.write("rollout.jsonl", "".join(json.dumps(row) + "\n" for row in (
        {"type": "session_meta", "payload": {"id": "thread-acme", "cwd": cwd}},
        {"type": "event_msg", "timestamp": "2026-11-05T10:00:00Z", "payload": {
            "type": "item_completed", "item": {"type": "UserMessage", "content": [
                {"type": "text", "text": FIRST}]}}})))
    receipt = home.write(f".agentkit/state/codex-launch-{TOKEN}.json", {
        "launch": TOKEN, "cwd": cwd, "event": {
            "session_id": "thread-acme", "transcript_path": str(rollout),
            "hook_event_name": "SessionStart", "source": "startup", "cwd": cwd}})
    return receipt, rollout


class DoneWaitsForTheCheck(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        seat = Seat(home, "acme", alive=False, record={"conversation": CONVERSATION})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        self.transcript = home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", "")
        self.converse(FIRST, SECOND)
        home.write(".agentkit/state/plan-acme.md", f"- [x] {PLANNED} · check: `true` · acme · "
                                                   "written 2026-11-05 10:05 · done 0123456789ab\n")

    def configure(self, on=True):
        akconfig.write(self.home, ["opus"], extra='[done_check]\nmodel = "opus"'
                                                  + ("" if on else "\non = false"))

    def converse(self, *asked):
        """The seat's conversation: each of the owner's messages in `asked`, a minute apart,
        each answered."""
        turns = []
        for text in asked:
            turns += [{"type": "user", "message": {"role": "user", "content": text}},
                      {"type": "assistant", "message": {"role": "assistant", "content": [
                          {"type": "text", "text": "Done."}]}}]
        self.transcript.write_text("".join(
            json.dumps({**turn, "timestamp": f"2026-11-05T10:{n:02d}:00Z"}) + "\n"
            for n, turn in enumerate(turns)))

    def why(self, name="acme", home=None):
        done = (home or self.home).ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out.splitlines()[0]

    def plan(self, step=None):
        """`ak plan` as the seat runs it, the model's turn doing `step` if it takes one."""
        if step:
            self.fake.behave(step)
        done = self.home.ak("plan", env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out

    def hook(self, script, payload):
        done = self.home.run("bash", str(ROOT / "hooks" / script), input=json.dumps(payload),
                             env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def stop(self):
        """The reason a turn the owner's prompt began is sent back with at its end, or "" where
        its stop stands."""
        self.hook("seat-state.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "go",
                                    "session_id": CONVERSATION})
        out = self.hook("orchestrator-stop.sh", {"hook_event_name": "Stop",
                                                 "session_id": CONVERSATION,
                                                 "transcript_path": str(self.transcript)})
        return json.loads(out)["reason"] if out.strip() else ""

    def test_a_finished_plan_reads_done_once_a_check_finds_no_gap(self):
        self.configure()
        self.assertNotEqual(self.why(), DONE)
        self.assertNotEqual(self.stop(), "")
        out = self.plan(GAP)
        self.assertEqual(self.fake.n, 1)
        self.assertIn(SECOND, out)
        self.assertNotEqual(self.why(), DONE)
        self.converse(FIRST, SECOND, DROP)
        out = self.plan(NONE)
        self.assertEqual(self.fake.n, 2)
        self.assertNotIn(SECOND, out)
        self.assertEqual(self.why(), DONE)
        self.assertEqual(self.stop(), "")
        self.plan()
        self.assertEqual(self.fake.n, 2)

    def test_a_check_that_could_not_be_made_counts_for_nothing(self):
        self.configure()
        self.plan(NONE)
        self.assertEqual(self.why(), DONE)
        self.fake.behave("silent")      # its turn never hands in done
        self.assertEqual(self.home.ak("orch", "check", "acme").code, 2)
        self.assertNotEqual(self.why(), DONE)
        self.plan(NONE)
        self.assertEqual(self.fake.n, 3)

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_a_check_ending_on_a_gap_after_a_rename_stands_under_the_new_name(self):
        self.configure()
        Seat(self.home, "acme", record={"conversation": CONVERSATION})      # one tmux holds
        self.plan(NONE)
        begun, release = self.fake.dir / "begun", self.fake.dir / "release"
        wait = shlex.quote(f"while test ! -f {shlex.quote(str(release))}; do sleep 0.02; done")
        self.fake.behave({**GAP, "sh": f"touch {shlex.quote(str(begun))}; timeout 30 sh -c "
                                       f"{wait}; {GAP['sh']}"})
        checking = self.home.spawn("orch", "check", "acme")
        try:
            until = time.monotonic() + 30
            while not begun.exists():
                self.assertIsNone(checking.poll(), "the check ended before its turn began")
                self.assertLess(time.monotonic(), until, "the check's turn never began")
                time.sleep(0.02)
            renamed = self.home.ak("orch", "rename", "acme", "acme-renamed")
            self.assertEqual(renamed.code, 0, renamed.out + renamed.err)
        finally:
            release.touch()
            checking.wait(timeout=60)
        self.assertEqual(checking.returncode, 1)
        self.assertNotEqual(self.why("acme-renamed"), "acme-renamed  done")

    def test_a_check_failing_as_it_looks_for_the_conversation_counts_for_nothing(self):
        with Home() as home:
            fake = fakeadapter.install(home, codex="pass", claude="pass")["claude"]
            Seat(home, "acme", model="astra", alive=False, record={"codex_launch": TOKEN})
            transcript = codex_seat(home)[1]
            home.write(".agentkit/state/plan-acme.md", f"- [x] {PLANNED}\n")
            akconfig.write(home, ["astra", "opus"], extra='[done_check]\nmodel = "opus"')
            self.assertEqual(home.ak("orch", "check", "acme").code, 0)
            kept = transcript.read_text()
            transcript.unlink()
            transcript.mkdir()      # Codex names its thread only once it reads the transcript
            self.assertEqual(home.ak("orch", "check", "acme").code, 2)
            transcript.rmdir()
            transcript.write_text(kept)
            fake.behave(NONE)
            done = home.ak("plan", env={"AGENTKIT_SESSION": "acme"})
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(fake.n, 2)

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_a_record_ak_cannot_read_holds_the_seat(self):
        self.configure()
        self.transcript.unlink()
        self.transcript.mkdir()
        self.assertNotEqual(self.why(), DONE)

        def directory(path):
            path.unlink()
            path.mkdir()

        opencode = ".agentkit/state/opencode-launch-" + TOKEN + "/session"
        for kind, (model, harness, unreadable) in {
                "an OpenCode database": ("mimo", "opencode", lambda home: home.write(
                    ".local/share/opencode/opencode.db", "not a SQLite database")),
                "an OpenCode launch receipt": ("mimo", "opencode", lambda home: directory(
                    home.path / opencode)),
                "an Antigravity database": ("gemini", "antigravity", lambda home: home.write(
                    ".gemini/antigravity-cli/conversations/conv-acme.db", "not a SQLite database")),
                "a Codex launch receipt": ("astra", "codex", lambda home: directory(
                    codex_seat(home)[0])),
                "a Codex launch receipt's JSON": ("astra", "codex", lambda home: codex_seat(
                    home)[0].write_text("{")),
                "a Codex transcript": ("astra", "codex", lambda home: directory(
                    codex_seat(home)[1])),
                "a Codex transcript's header": ("astra", "codex", lambda home: (
                    lambda rollout: rollout.write_text("{\n" + rollout.read_text().split(
                        "\n", 1)[1]))(codex_seat(home)[1]))}.items():
            with self.subTest(kind), Home() as home:
                fakeadapter.install(home, **{harness: "pass", "claude": "pass"})
                Seat(home, "acme", model=model, screen=f"{harness}-prompt-pane.txt",
                     record={"opencode_launch": TOKEN, "codex_launch": TOKEN})
                home.write(opencode, "ses_acme")
                unreadable(home)
                home.write(".agentkit/state/plan-acme.md", f"- [x] {PLANNED}\n")
                akconfig.write(home, [model, "opus"], extra='[done_check]\nmodel = "opus"')
                self.assertNotEqual(self.why(home=home), DONE)

    def test_with_the_check_off_a_finished_plan_reads_done_and_ak_plan_takes_no_turn(self):
        self.configure(on=False)
        self.assertEqual(self.why(), DONE)
        self.plan()
        self.assertEqual(self.fake.n, 0)

    def test_a_seat_nobody_is_in_owing_only_its_check_rests(self):
        """Only the seat's own `ak plan` makes its check: it is not the owner's, and no reboot
        reopens a seat for it."""
        self.configure()
        self.assertEqual(self.why(), "acme  idle")
        self.home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        self.home.write(".agentkit/state/watch.json", {"boot_id": "before"})
        tick = self.home.ak("watch", "--dry-run")
        self.assertEqual(tick.code, 0, tick.out + tick.err)
        self.assertNotIn("would resume acme after reboot", tick.out)


if __name__ == "__main__":
    unittest.main()
