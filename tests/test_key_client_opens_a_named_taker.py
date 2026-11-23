"""A client whose home does not answer opens the menu of a machine its home named as taking over.

A client's own `ak` hops as `ssh -t HOME ak --client`, and where its list names any machine, as
`ssh -o ConnectTimeout=10 -t HOME ak --client`, each name tried too: a home without power refuses
nothing, and ssh would wait on it for over a minute.  Where the hop exits anything but 255, the
home answered, and is asked whom it names (`ak standby --takers`,
tests/test_key_standby_names_its_takers.py): an answer that exits 0, every line of it a host name,
replaces the list ak keeps at ~/.agentkit/tmp/takers whole, none among them; any other, or none
within ten seconds, leaves it, and `ak` exits as the hop did.  Where the hop exits 255, ssh
reached no machine, and each machine the list, read before the hop, names is tried in its order,
nothing asked of it: the first that does not exit 255 is `ak`'s exit, and with none,
255.  A last name needs no newline; a list holding any other line, or that is no regular file,
names none.  `ak --client` and `ak --dry-run` try no list, nor give ssh ten seconds.
Black-box: the program `AK_BIN` names runs on a Home of tests/fixtures/akbin.py, with a fake ssh
that logs its arguments and answers as each test scripts the machine it is given, by whether it
is given `-t`.
"""

import os
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, Home

HOME = "acme-mini"
MACHINES = (HOME, "acme-a", "acme-vm", "acme-x", "acme-new")
LIST = ".agentkit/tmp/takers"
# ak's own exits are 0, 1, 2 and 130, so a 7 can only be ssh's, handed on
SSH = LOG + """for a do
  case $a in {machines}) machine=$a ;; -t) tty=.t ;; esac
done
answer={answers}/$machine${{tty-}}
[ -f "$answer" ] || exit 9
. "$answer"
"""


def hop(machine, listed):
    """ssh's words for the menu of `machine`, given ten seconds to connect where the list names
    any machine."""
    return ["-o", "ConnectTimeout=10"] * listed + ["-t", machine, "ak", "--client"]


class AClientOpensANamedTaker(unittest.TestCase):
    def setUp(self):
        self.client = Home()
        self.addCleanup(self.client.close)
        self.client.write(".agentkit/state/server", f"{HOME}\n")
        self.answers = self.client.root / "answers"
        self.answers.mkdir()
        self.client.fake("ssh", SSH.format(
            python=shlex.quote(sys.executable), log=shlex.quote(str(self.client.log("ssh"))),
            machines="|".join(MACHINES), answers=shlex.quote(str(self.answers))))

    def answer(self, machine, tty, code, printed="", silent=False):
        """Script ssh given `machine`, with `-t` or without: print `printed` and exit `code`, or,
        `silent`, print nothing for a minute, past any ceiling."""
        said = "exec sleep 60\n" if silent else f"printf %s {shlex.quote(printed)}\nexit {code}\n"
        (self.answers / (machine + (".t" if tty else ""))).write_text(said)

    def ak(self, *args):
        """`ak args` on the client: its exit, and each argv ssh was called with meanwhile."""
        before = len(self.client.calls("ssh"))
        done = self.client.ak(*args)
        return done.code, self.client.calls("ssh")[before:]

    def kept(self):
        path = self.client.path / LIST
        return path.read_bytes() if path.exists() else None

    def test_a_home_that_answers_names_them_and_one_that_does_not_opens_the_first_reached(self):
        self.answer(HOME, True, 0)
        self.answer(HOME, False, 0, "acme-a\nacme-vm\n")
        code, calls = self.ak()
        self.assertEqual((code, len(calls), calls[:1]), (0, 2, [hop(HOME, listed=False)]))
        self.assertEqual(self.kept(), b"acme-a\nacme-vm\n")
        self.answer(HOME, True, 255)
        self.answer("acme-a", True, 255)
        self.answer("acme-vm", True, 7)
        self.assertEqual(self.ak(), (7, [hop(HOME, listed=True), hop("acme-a", listed=True),
                                         hop("acme-vm", listed=True)]))
        self.assertEqual(self.kept(), b"acme-a\nacme-vm\n")

    def test_an_answer_but_names_that_exited_0_leaves_the_list(self):
        self.client.write(LIST, "acme-a\nacme-vm\n")
        self.answer(HOME, True, 7)
        for name, answer in (("failed", (1, "acme-x\n")), ("silent", (0,)),
                             ("an option", (0, "acme-x\n-oProxyCommand=x\n"))):
            with self.subTest(name):
                self.answer(HOME, False, *answer, silent=name == "silent")
                self.assertEqual(self.ak()[0], 7)
                self.assertEqual(self.kept(), b"acme-a\nacme-vm\n")

    def test_no_names_empty_the_list_and_then_none_is_tried(self):
        self.client.write(LIST, "acme-vm\n")
        self.answer("acme-vm", True, 0)
        self.answer(HOME, True, 0)
        self.answer(HOME, False, 0)
        asking = ["-o", "BatchMode=yes", HOME, '"$HOME"/.local/bin/ak standby --takers']
        self.assertEqual(self.ak(), (0, [hop(HOME, listed=True), asking]))
        self.assertEqual(self.kept(), b"")
        self.answer(HOME, True, 255)
        self.assertEqual(self.ak(), (255, [hop(HOME, listed=False)]))

    def test_no_list_or_one_holding_another_line_names_none(self):
        self.answer("acme-vm", True, 0)
        self.answer(HOME, True, 255)
        self.assertEqual(self.ak(), (255, [hop(HOME, listed=False)]))
        self.client.write(LIST, "acme-vm\n-oProxyCommand=x\n")
        self.assertEqual(self.ak(), (255, [hop(HOME, listed=False)]))
        (self.client.path / LIST).unlink()
        os.mkfifo(self.client.path / LIST)     # which no writer ever opens
        self.assertEqual(self.ak(), (255, [hop(HOME, listed=False)]))

    def test_a_last_name_needs_no_newline(self):
        self.client.write(LIST, "acme-vm")
        self.answer("acme-vm", True, 7)
        self.answer(HOME, True, 255)
        self.assertEqual(self.ak(), (7, [hop(HOME, listed=True), hop("acme-vm", listed=True)]))
        self.answer(HOME, True, 0)
        self.answer(HOME, False, 0, "acme-a\nacme-new")
        self.assertEqual(self.ak()[0], 0)
        self.answer(HOME, True, 255)
        self.answer("acme-a", True, 255)
        self.answer("acme-new", True, 7)
        self.assertEqual(self.ak(), (7, [hop(HOME, listed=True), hop("acme-a", listed=True),
                                         hop("acme-new", listed=True)]))

    def test_client_and_dry_run_try_no_list(self):
        self.client.write(LIST, "acme-vm\n")
        self.answer("acme-vm", True, 0)
        for code in (255, 0):
            with self.subTest(code=code):
                self.answer(HOME, True, code)
                self.assertEqual(self.ak("--client"),
                                 (code, [hop(HOME, listed=False) + ["--client"]]))
        self.assertEqual(self.ak("--dry-run"), (0, []))


if __name__ == "__main__":
    unittest.main()
