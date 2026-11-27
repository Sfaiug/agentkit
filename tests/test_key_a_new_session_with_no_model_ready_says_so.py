"""A new seat on a model whose harness's program is not installed is refused where it would
start, before a session is saved or a program starts: Enter on the new row (with no program
installed, or with a model picked by hand on `tab models` whose program is missing) and the
line prompt show why and save no seat, a dry run of either the same, and `ak orch NAME --model`
of such a model, or `ak orch NAME` where no model's program is installed, `--dry-run` or not,
prints it, exits as a refusal does and saves and starts nothing.  Automatic inbox and audit
seats started by `ak watch` refuse the same way without asking the adapter or saving a seat.
With the program installed the seat starts; the refusals that came first before -- a name held,
every model off, the model off -- still do.

A newcomer with no program installed got a seat whose pane said only "The harness ended." (26 Nov
2026).  Black-box: the program `AK_BIN` names runs from outside (tests/fixtures/akbin.py), its
menu on a terminal of tests/fixtures/akterm.py, its harnesses tests/fixtures/fakeadapter.py's; a
program is missing once its manifest names it at a path where nothing is, so none the host
installed stands in for it.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

ROW_KEYS = "  ⏎ start   tab models   esc back"
PICKER_KEYS = "  ↑↓←→ move   ␣ mark   ⏎ start   esc back"
HINT = "is not installed on this machine; ./install.sh, run in a terminal, installs it"
REFUSED = f"new session: opus: claude {HINT}"
DRY = ((), ("--dry-run",))
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


class NoModelReady(unittest.TestCase):
    """opus, on claude, orchestrates by default; astra, on codex, is the other model."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, ["opus", "astra"])

    def uninstall(self, *harnesses):
        """Each harness's manifest names its program where nothing is."""
        for harness in harnesses:
            manifest, named = self.fakes[harness].manifest, f'version = ["{harness}", '
            self.assertEqual(manifest.read_text().count(named), 1,
                             f"the shipped {harness}.toml's [update] changed")
            gone = fakeadapter.toml(str(self.home.root / "gone" / harness))
            manifest.write_text(manifest.read_text().replace(named, f"version = [{gone}, "))

    def seats(self):
        return sorted(path.name for path in (self.home.path / ".agentkit/state").glob("session-*"))

    def launched(self):
        return [call for fake in self.fakes.values() for call in fake.calls("interactive")]

    def row(self, *args):
        """The menu (`ak` and `args`), with fix-api typed in the new row."""
        menu = Terminal(self.home, *args, size=(100, 40), env={"NO_COLOR": "1"})
        menu.wait("esc leave")
        menu.keys("n")
        menu.wait(ROW_KEYS)
        menu.type("fix-api")
        menu.wait("fix-api")
        return menu

    def refused(self, menu):
        """Wait for the refusal, framed or printed as the line the terminal wraps."""
        menu.wait(lambda _: REFUSED in " ".join(menu.screen(copied=True).split()))

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_enter_on_the_new_row_says_why_and_saves_no_seat(self):
        self.uninstall("claude", "codex")
        menu = self.row()
        menu.keys("Enter")
        self.refused(menu)
        self.assertEqual(self.seats(), [])
        self.assertEqual(self.launched(), [])
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=fix-api").code, 0)

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_the_new_rows_dry_run_says_the_same(self):
        self.uninstall("claude", "codex")
        menu = self.row("attach", "--dry-run")
        menu.keys("Enter")
        self.refused(menu)
        self.assertEqual(self.seats(), [])
        self.assertEqual(self.launched(), [])

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_picking_a_model_whose_program_is_missing_on_tab_models_is_refused(self):
        self.uninstall("claude")
        menu = self.row()
        menu.keys("Tab")
        menu.wait(PICKER_KEYS)
        # opus is first on the picker (cursor starts on it); mark it to orchestrate and start
        menu.keys("Space")
        menu.wait(lambda screen: any("Opus 5.5" in line and "[●]" in line
                                     for line in screen.splitlines()))
        menu.keys("Enter")
        self.refused(menu)
        self.assertEqual(self.seats(), [])
        self.assertEqual(self.launched(), [])
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=fix-api").code, 0)

    def test_the_line_prompt_says_why_and_saves_no_seat_dry_run_or_not(self):
        self.uninstall("claude", "codex")
        for dry in DRY:
            with self.subTest(dry=dry):
                # n, the name, Enter for each default, and the note read
                done = self.home.ak("attach", *dry, input="n\nfix-api\n\n\n\n\n")
                self.assertIn(REFUSED + "\n", done.out)
                self.assertEqual(self.seats(), [])
                self.assertEqual(self.launched(), [])

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_enter_on_the_new_row_starts_the_seat_with_its_program_installed(self):
        menu = self.row()
        menu.keys("Enter")
        path = self.home.path / ".agentkit/state/session-fix-api.json"
        deadline = time.monotonic() + 30
        while True:
            listed = self.home.tmux("list-sessions", "-F", "#{session_name} #{session_attached}")
            if "fix-api 1" in listed.out.splitlines() and path.exists():
                break
            screen = menu.screen()
            self.assertNotIn("new session:", screen,
                             f"fix-api was refused; the terminal shows:\n{screen}")
            self.assertLess(time.monotonic(), deadline,
                            f"fix-api never started; tmux holds {listed.out!r} and the terminal "
                            f"shows:\n{screen}")
            time.sleep(0.05)
        self.assertEqual(json.loads(path.read_text())["orchestrator"], "opus")
        self.assertTrue(self.fakes["claude"].calls("interactive"))

    def refused_by_orch(self, picked, said, answers):
        """`ak orch fix-api` and `picked` say `said`, a dry run or not, saving and starting
        nothing."""
        for dry in DRY:
            with self.subTest(picked=picked, dry=dry):
                # typed at a terminal, only a person's `ak orch` opens a seat
                done = self.home.ak("orch", "fix-api", *picked, *dry, tty=not dry, input=answers)
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertEqual(done.err, f"ak orch: {said} {HINT}\n")
                self.assertEqual(self.seats(), [])
                self.assertEqual(self.launched(), [])
                if REAL_TMUX:
                    self.assertNotEqual(self.home.tmux("has-session", "-t", "=fix-api").code, 0)

    def test_a_model_picked_by_name_whose_program_is_missing_is_refused(self):
        self.uninstall("codex")
        self.refused_by_orch(("--model", "astra"), "astra: codex", "\n")

    def test_the_default_pick_with_no_program_installed_is_refused(self):
        self.uninstall("claude", "codex")
        self.refused_by_orch((), "opus: claude", "\n\n")

    def test_a_dry_run_of_a_model_whose_program_is_installed_goes_ahead(self):
        self.uninstall("claude")
        done = self.home.ak("orch", "fix-api", "--model", "astra", "--dry-run")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("orch: astra (--model)", done.out)

    def test_every_model_off_is_still_said_first(self):
        self.uninstall("claude", "codex")
        akconfig.write(self.home, ["opus", "astra"],
                       settings={"models_off": ["claude-opus-5-5", "gpt-6-astra"]})
        for named in ((), ("--model", "astra")):
            with self.subTest(named=named):
                done = self.home.ak("orch", "fix-api", *named, "--dry-run")
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertIn("every model is off in the model list", done.err)

    def test_a_model_off_is_still_said_before_its_program_is_missing(self):
        self.uninstall("codex")
        akconfig.write(self.home, ["opus", "astra"], settings={"models_off": ["gpt-6-astra"]})
        done = self.home.ak("orch", "fix-api", "--model", "astra", "--dry-run")
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertIn("astra is off in the model list", done.err)

    def test_a_signed_out_account_is_still_refused_first(self):
        for installed in (True, False):
            if not installed:
                self.uninstall("claude")
            for off in (False, True):
                with self.subTest(installed=installed, off=off):
                    akconfig.write(
                        self.home, ["opus", "astra"],
                        providers={"anthropic": {"mode": "subscription", "accounts": ["acme"]}},
                        settings={"models_off": ["claude-opus-5-5"]} if off else {})
                    self.fakes["claude"].answer("auth", "signed out", code=1, given=("seat",))
                    done = self.home.ak("orch", "fix-api", "--model", "opus",
                                        "--workers", "astra", "--dry-run")
                    self.assertEqual(done.code, 2, done.out + done.err)
                    self.assertEqual(done.err,
                                     "ak orch: anthropic: no account has a working seat login\n")

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_the_new_rows_dry_run_refuses_an_off_model_picked_on_tab_models(self):
        path = akconfig.write(self.home, ["opus", "astra"], workers=[],
                              settings={"models_off": ["claude-opus-5-5"]})
        path.write_text(path.read_text().replace("[defaults]\n", "[defaults]\nreviewers = []\n", 1))
        menu = self.row("attach", "--dry-run")
        menu.keys("Tab")
        menu.wait(PICKER_KEYS)
        menu.keys("Space")
        menu.wait(lambda screen: any("Opus 5.5" in line and "[●]" in line
                                     for line in screen.splitlines()))
        menu.keys("Enter")
        menu.wait(lambda _: "new session: opus is off in the model list"
                  in " ".join(menu.screen(copied=True).split()))
        self.assertEqual(self.seats(), [])

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_a_name_held_by_tmux_is_still_said_first(self):
        self.uninstall("claude", "codex")
        held = self.home.tmux("-f", "/dev/null", "new-session", "-d", "-s", "fix-api", "sleep 60")
        self.assertEqual(held.code, 0, held.err)
        done = self.home.ak("orch", "fix-api", "--model", "astra", "--dry-run")
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertIn("tmux already holds a session named 'fix-api'", done.err)

    def test_an_automatic_audit_seat_whose_program_is_missing_is_refused(self):
        self.uninstall("codex")
        akconfig.write(
            self.home, ["opus", "astra"], audit=None,
            extra='[audit]\non = true\norchestrator = "astra"\n'
                  'workers = ["opus"]\nreviewers = ["opus"]\n')
        self.home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        done = self.home.ak("watch", env=OFFLINE)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn(f"astra: codex {HINT}", done.out + done.err)
        self.assertEqual(self.seats(), [])
        self.assertEqual(self.launched(), [])
        if REAL_TMUX:
            self.assertNotEqual(self.home.tmux("has-session", "-t", "=audit").code, 0)

    def test_an_automatic_inbox_seat_with_no_program_installed_is_refused(self):
        self.uninstall("claude", "codex")
        self.home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        self.home.write(".agentkit/runs/20261127-1000-fix-api/run.json", {
            "run_id": "20261127-1000-fix-api",
            "title": "Fix API",
            "state": "pass",
            "reported": True,
            "handed_back": True,
            "pending_inbox": {
                "question": "PR #9 by bob: Fix API. Merge? yes/no",
                "url": "https://example.test/pr/9",
                "sha": "a" * 40,
                "asked": False,
            },
        })
        done = self.home.ak("watch", env=OFFLINE)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn(f"opus: claude {HINT}", done.out + done.err)
        self.assertEqual(self.seats(), [])
        self.assertEqual(self.launched(), [])
        if REAL_TMUX:
            self.assertNotEqual(self.home.tmux("has-session", "-t", "=inbox").code, 0)

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_automatic_seat_follows_the_installed_checkout_s_adapters(self):
        for harness, installed in (("acme", True), ("claude", False)):
            with self.subTest(harness=harness, installed=installed), Home() as home:
                akconfig.write(home, {"alpha": harness}, audit=True)
                program = (home.fake(harness, "#!/bin/sh\nexec sleep 60\n")
                           if installed else home.path / "missing" / harness)
                called = home.path / "interactive-called"
                adapter = home.write(
                    f"agentkit/adapters/{harness}.sh",
                    f'#!/bin/sh\n[ "$1" = interactive ] || exit 2\n'
                    f'touch "{called}"\nprintf "%s\\n" "{program}"\n')
                adapter.chmod(0o755)
                home.write(
                    f"agentkit/adapters/{harness}.toml",
                    f'[update]\nversion = [{fakeadapter.toml(str(program))}, "--version"]\n')
                home.write(".agentkit/state/gc.json", {"started_at": time.time()})
                done = home.ak("watch", env=OFFLINE)
                self.assertEqual(done.code, 0, done.out + done.err)
                saved = (home.path / ".agentkit/state/session-audit.json").is_file()
                self.assertEqual((called.is_file(), saved), (installed, installed),
                                 done.out + done.err)


if __name__ == "__main__":
    unittest.main()
