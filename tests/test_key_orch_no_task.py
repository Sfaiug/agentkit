"""`ak orch` as a person and a seat type it with no task: flags refused before any question, a
name asked for or left to ak, and `ak orch rename NEW` from inside a seat.

A model or worker the config lacks is refused before ak asks anything, so nobody answers a
question for a seat that cannot open.  With no name, ak asks `Name (Enter: auto):`; a name a
seat or a rename already holds is asked again, Esc goes back, and Enter or the end of input
opens the seat under a character name its orchestrator replaces with `ak orch rename --auto`
once it knows the work.  Inside a seat one name renames that seat, whichever of its names the
seat was started with.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, with a terminal on its stdin, in tests/fixtures/akterm.py's terminal
or beside tests/fixtures/akseat.py's seats; this test fails against `/bin/false`.
"""

import re
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, REPO, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

ASK = "Name (Enter: auto): "
DRY = ("orch", "--dry-run", "--model", "opus", "--workers", "opus")
UNKNOWN = "ak orch: unknown model 'nosuch'; ~/.agentkit/config.toml defines: opus, spark\n"
# A model whose harness is tests/fixtures/adapters/echo.sh: its seat is a shell.
ECHO = """[defaults]
orchestrator = "echo"
workers = ["echo"]

[models.echo]
harness = "echo"
model = "echo-1"
effort = "low"
provider = "test"

[providers.test]
mode = "subscription"
"""


def records(home):
    return sorted(path.name for path in (home.path / ".agentkit/state").glob("session-*.json"))


def held(home):
    """The sessions ak's tmux holds, none where its server never started."""
    return sorted(home.tmux("list-sessions", "-F", "#{session_name}").out.split())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FlagsFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus", "spark"])

    def test_a_model_the_config_lacks_is_refused_before_any_question(self):
        for args in (("acme", "--model", "nosuch", "--workers", "opus"),
                     ("acme", "--model", "opus", "--workers", "nosuch"),
                     ("acme", "--model", "nosuch"), ("acme", "--workers", "nosuch"),
                     ("--model", "nosuch"), ("--workers", "nosuch")):
            with self.subTest(args=args):
                # the Enter typed would answer a question, had one been asked
                done = self.home.ak("orch", *args, input="\n", tty=True)
                self.assertEqual((done.code, done.out, done.err), (2, "", UNKNOWN))
        self.assertEqual(records(self.home), [])
        self.assertEqual(held(self.home), [])

    def test_a_worker_list_it_cannot_read_is_refused_before_any_question(self):
        for workers, error in (("opus,opus", "--workers contains duplicate model names"),
                               ("", "--workers needs a comma-separated list of model names")):
            for args in (("acme", "--workers", workers),
                         ("acme", "--model", "opus", "--workers", workers)):
                with self.subTest(args=args):
                    done = self.home.ak("orch", *args, input="\n", tty=True)
                    self.assertEqual((done.code, done.out, done.err),
                                     (2, "", f"ak orch: {error}\n"))
        self.assertEqual(records(self.home), [])


class NameQuestion(unittest.TestCase):
    """A dry run, which opens and saves nothing, beside a seat `acme` once called `old`."""

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        Seat(cls.home, "acme", alive=False)
        cls.home.write(".agentkit/state/session-old.json", {"renamed": "acme"})

    def asked(self, typed):
        """What the dry run printed, the command it would run aside, once `typed` answers."""
        done = self.home.ak(*DRY, input=typed, tty=True)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(records(self.home), ["session-acme.json", "session-old.json"])
        return done.out.splitlines()[:-1] if "orch: " in done.out else done.out.splitlines()

    def opened(self, name):
        return ["orch: opus (--model)", f"session {name} in {self.home.path} (new)",
                "workers opus"]

    def test_a_name_typed_at_the_question_names_the_seat(self):
        self.assertEqual(self.asked("Fix API\n"), [ASK, *self.opened("fix-api")])

    def test_a_name_a_seat_or_a_rename_holds_is_asked_for_again(self):
        self.assertEqual(self.asked("acme\nold\nfix-api\n"), [
            ASK, "a session named acme is already there; pick another name",
            ASK, "a session named old is already there; pick another name",
            ASK, *self.opened("fix-api")])

    def test_enter_or_the_end_of_input_leaves_the_name_to_ak(self):
        for typed in ("\n", "   \n", "\x04"):
            with self.subTest(typed=typed):
                said = self.asked(typed)
                self.assertEqual(said[0], ASK)
                found = re.fullmatch(rf"session (\S+) in {re.escape(str(self.home.path))} "
                                     r"\(new\)", said[2])
                self.assertIsNotNone(found, said)
                name = found[1]
                self.assertRegex(name, r"^[a-z]+$")     # one word, a character's
                self.assertNotIn(name, ("acme", "old"))
                self.assertEqual(said[1:], self.opened(name))

    def test_esc_goes_back_and_opens_nothing(self):
        self.assertEqual(self.asked("\x1b\n"), [ASK])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpenedWithoutAName(unittest.TestCase):
    def test_enter_opens_a_seat_its_orchestrator_names_once_it_knows_the_work(self):
        with Home() as home:
            home.write(".agentkit/config.toml", ECHO)
            adapters = home.root / "adapters"
            shutil.copytree(REPO / "tests/fixtures/adapters", adapters)
            env = {"AGENTKIT_ADAPTER_DIR": str(adapters)}
            person = Terminal(home, "orch", "--model", "echo", "--workers", "echo", env=env)
            self.assertEqual(person.wait(ASK.strip()).strip(), ASK.strip())
            person.keys("Enter")
            person.wait(lambda screen: len(held(home)) == 1, bound=60)
            name = held(home)[0]
            self.assertRegex(name, r"^[a-z]+$")
            self.assertEqual(records(home), [f"session-{name}.json"])
            # the person's terminal is in the seat now
            person.wait(lambda screen: home.tmux("list-clients", "-F", "#{session_name}").out
                        == f"{name}\n")
            inside = {**env, "AGENTKIT_SESSION": name}
            done = home.ak("orch", "rename", "--auto", "parser-fix", env=inside)
            self.assertEqual((done.code, done.out), (0, f"renamed {name} -> parser-fix\n"),
                             done.err)
            self.assertEqual(held(home), ["parser-fix"])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RenameInside(unittest.TestCase):
    def test_one_name_inside_a_seat_renames_that_seat_under_any_name_it_had(self):
        with Home() as home:
            seat = Seat(home, "fix-api")
            inside = {"AGENTKIT_SESSION": "fix-api"}
            # the orchestrator keeps the name it was started with after the first rename
            for old, new in (("fix-api", "lagoon"), ("lagoon", "reef")):
                with self.subTest(new=new):
                    done = home.ak("orch", "rename", new, env=inside)
                    self.assertEqual((done.code, done.out, done.err),
                                     (0, f"renamed {old} -> {new}\n", ""))
                    shown = home.tmux("display-message", "-p", "-t", seat.pane,
                                      "#{session_name}")
                    self.assertEqual(shown.out, f"{new}\n")
                    self.assertEqual(held(home), [new])


if __name__ == "__main__":
    unittest.main()
