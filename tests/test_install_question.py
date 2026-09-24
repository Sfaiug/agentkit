"""install.sh asks one question, and one provider finishes the install.

On a machine with none of the harnesses installed, a terminal run asks once which
to install and log in -- one of the adapters present, or all -- and only those go
in.  With no terminal there is nobody to ask, so nothing is installed and each
adapter only says whether it is logged in and the command that logs it in.  A run
on a machine that has one keeps what it has and adds none unasked.  The closing
summary stays the pending list, one line per missing thing.

Offline: section (3) and the pending section of the real install.sh, run against
fixture adapters and a fixture PATH, with the answer on stdin.  The runs that
look at the question itself hold a pty, because `read -p` shows its prompt only
on a terminal.  No package, no network, no real harness, no HOME outside the
fixture.
"""

import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]

# Display name -> adapter file stem.  grokbuild's binary is grok, so that is the
# name it is offered under.
ADAPTERS = (("claude", "claude"), ("codex", "codex"), ("muse", "muse"),
            ("grok", "grokbuild"), ("opencode", "opencode"), ("agy", "antigravity"))

# A harness that is never logged in, in the shape the real adapters answer a
# login probe with: one line saying so and the command, on a failing exit.
FAKE_ADAPTER = """#!/bin/sh
# /bin/sh, not env bash: the slice runs on a fixture PATH with no shell on it.
echo "{stem} $1" >>"$FAKE_ADAPTER_LOG"
case $1 in
  install) echo "{stem}: installed" ;;
  login) echo "{stem}: not logged in; run \\`{stem} login\\` in a terminal"; exit 1 ;;
  *) echo "fake adapter: no $1" >&2; exit 2 ;;
esac
"""


class InstallQuestion(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".install-question-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.adapters = self.root / "repo" / "adapters"
        self.adapters.mkdir(parents=True)
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.log = self.root / "adapter.log"
        # The harness slice needs tr for the answer's case and whitespace; the
        # pending slice needs stat, date and grep for its expiry arithmetic and its
        # count.  Nothing else is on PATH, so no real harness, gh or tailscale -- all
        # present on a developer box -- is in reach of the slice.
        for tool in ("tr", "stat", "date", "grep"):
            target = shutil.which(tool)
            self.assertIsNotNone(target, f"no {tool} on this box")
            (self.bindir / tool).symlink_to(target)
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash, "no bash on this box")

    def adapter(self, stem):
        path = self.adapters / f"{stem}.sh"
        path.write_text(FAKE_ADAPTER.format(stem=stem))
        path.chmod(0o755)

    def binary(self, name):
        """A harness binary on PATH, so the box counts as having that harness."""
        path = self.bindir / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)

    def child_env(self):
        return {**os.environ, "HOME": str(self.home), "PATH": str(self.bindir),
                "FAKE_ADAPTER_LOG": str(self.log)}

    def slice_script(self, start, end, tty):
        """Section (3), or the pending section, of the real install.sh."""
        source = (REPO / "install.sh").read_text()
        begin = source.index(start)
        block = source[begin:] if end is None else source[begin:source.index(end, begin + 1)]
        ak = self.home / ".agentkit"
        (ak / "secrets").mkdir(parents=True, exist_ok=True)
        return (
            "set -euo pipefail\n"
            f"REPO={shlex.quote(str(self.root / 'repo'))}\n"
            f"AK={shlex.quote(str(ak))}\n"
            "ROLE=server\nSANDBOX=0\nALIAS=\nOS=Linux\n"
            f"TTY={tty}\n"
            "have() { command -v \"$1\" >/dev/null 2>&1; }\n"
            "note() { echo \"note: $*\" >&2; }\n"
            f"{block}"
        )

    def run_slice(self, start, end, tty, answer):
        script = self.slice_script(start, end, tty)
        return subprocess.run([self.bash, "-c", script], input=answer,
                              capture_output=True, text=True, env=self.child_env(),
                              cwd=str(self.root))

    def run_harnesses(self, tty, answer):
        return self.run_slice("# --- (3) the harnesses", "\n# --- (3b)", tty, answer)

    def run_harnesses_pty(self, answer, tty=1, limit=10.0):
        """Section (3) with a terminal on stdin and stdout, playing the answer.

        `read -p` shows its prompt only on a terminal, so a pipe-driven run can
        never see the question; this one reads it off the pty.  `answer` goes
        down with the first output -- the pty holds it until the read -- or not
        at all when None.  Returns (returncode, output); a run still going at
        `limit` seconds is killed.
        """
        script = self.slice_script("# --- (3) the harnesses", "\n# --- (3b)", tty)
        master, slave = pty.openpty()
        proc = subprocess.Popen([self.bash, "-c", script], stdin=slave, stdout=slave,
                                stderr=slave, env=self.child_env(), cwd=str(self.root))
        os.close(slave)
        self.addCleanup(proc.kill)
        out, sent, started = bytearray(), answer is None, time.monotonic()
        try:
            while True:
                if time.monotonic() - started > limit:
                    proc.kill()
                    break
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    out += chunk
                    if not sent:
                        try:
                            os.write(master, answer.encode())
                        except OSError:
                            pass
                        sent = True
                elif proc.poll() is not None:
                    break
        finally:
            os.close(master)
        return proc.wait(timeout=10), out.decode("utf-8", "replace")

    def calls(self):
        if not self.log.exists():
            return []
        return self.log.read_text().splitlines()

    def all_adapters(self):
        for _, stem in ADAPTERS:
            self.adapter(stem)

    # --- the question ------------------------------------------------------

    def test_question_lists_the_adapters_present(self):
        # Over a pty: `read -p` shows its prompt only on a terminal, so a pipe
        # run would match the adapters' own echoes instead of the question.
        self.all_adapters()
        rc, question = self.run_harnesses_pty("all\n")
        self.assertEqual(rc, 0, question)
        self.assertIn("Which harness to install and log in "
                      "(claude, codex, muse, grok, opencode, agy, or all)? [all] ", question)
        self.assertEqual(len(self.calls()), 12)
        # An adapter file that is not there is not offered.
        (self.adapters / "muse.sh").unlink()
        self.log.unlink()
        rc, question = self.run_harnesses_pty("all\n")
        self.assertEqual(rc, 0, question)
        self.assertIn("Which harness to install and log in "
                      "(claude, codex, grok, opencode, agy, or all)? [all] ", question)
        self.assertNotIn("muse", question)
        self.assertEqual(len(self.calls()), 10)

    def test_all_selects_every_adapter_present(self):
        self.all_adapters()
        proc = self.run_harnesses(tty=1, answer="all\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(sorted(self.calls()),
                         sorted(f"{stem} {verb}" for _, stem in ADAPTERS
                                for verb in ("install", "login")))
        # ... and only the adapters present.
        (self.adapters / "codex.sh").unlink()
        self.log.unlink()
        proc = self.run_harnesses(tty=1, answer="all\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("codex install", self.calls())
        self.assertNotIn("codex login", self.calls())
        self.assertEqual(len(self.calls()), 10)

    def test_single_choice_installs_only_it(self):
        self.all_adapters()
        proc = self.run_harnesses(tty=1, answer="grok\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.calls(), ["grokbuild install", "grokbuild login"])
        # The answer is read forgivingly: case and surrounding whitespace do not
        # change which harness it names.
        self.log.unlink()
        proc = self.run_harnesses(tty=1, answer="  Codex\t\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.calls(), ["codex install", "codex login"])

    def test_empty_answer_installs_everything_present(self):
        self.all_adapters()
        proc = self.run_harnesses(tty=1, answer="\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(len(self.calls()), 12)

    def test_unknown_answer_installs_nothing(self):
        self.all_adapters()
        proc = self.run_harnesses(tty=1, answer="vim\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.calls(), [])
        self.assertIn("'vim' is not one of", proc.stderr)

    def test_installed_harness_skips_the_question(self):
        # The question is for a machine with none of the harnesses; with one on PATH
        # a re-run keeps what is installed -- those are checked and logged in -- and
        # adds none unasked.  Over a pty, so the missing prompt is a real absence
        # rather than a pipe hiding it.
        self.all_adapters()
        self.binary("claude")
        self.binary("grok")
        rc, out = self.run_harnesses_pty(None)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Which harness", out)
        self.assertEqual(self.calls(), ["claude install", "claude login",
                                        "grokbuild install", "grokbuild login"])
        # With no terminal it only says how the installed ones are logged in.
        self.log.unlink()
        proc = self.run_harnesses(tty=0, answer="")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.calls(), ["claude login", "grokbuild login"])

    # --- no terminal -------------------------------------------------------

    def test_non_interactive_asks_nothing_and_lists_the_commands(self):
        # Over a pty too: with no one to ask for, no prompt goes out even where
        # one could be shown.
        self.all_adapters()
        rc, out = self.run_harnesses_pty(None, tty=0)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Which harness", out)
        self.assertEqual([call for call in self.calls() if call.endswith(" install")], [])
        for _, stem in ADAPTERS:
            self.assertIn(f"{stem} login", self.calls())
            self.assertIn(f"run `{stem} login` in a terminal", out)

    # --- the closing summary -----------------------------------------------

    def test_pending_lists_one_line_per_missing_harness(self):
        self.all_adapters()
        proc = self.run_slice("# --- (i) what this run could not do", None, 0, "")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        items = [line for line in proc.stdout.splitlines() if line.startswith("  ")]
        for name, _ in ADAPTERS:
            self.assertEqual(len([line for line in items
                                  if f"{name} is not installed" in line]), 1)
        # Installed but not logged in is the same shape: one login line, no install line.
        for name, _ in ADAPTERS:
            self.binary(name)
        proc = self.run_slice("# --- (i) what this run could not do", None, 0, "")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        items = [line for line in proc.stdout.splitlines() if line.startswith("  ")]
        self.assertEqual([line for line in items if "is not installed" in line], [])
        for name, _ in ADAPTERS:
            self.assertEqual(len([line for line in items if f"{name} login --" in line]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
