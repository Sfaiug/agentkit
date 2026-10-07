"""A launch writes its seat's rulebook in its own process, and every adapter takes that file.

Every adapter's `interactive` ran `tools/rulebook.py`, which started a second Python and
imported all of agentkit to write the file on every new seat, reopen and model switch.  The
launch writes it before it asks and names it to the adapter, which runs the tool only when it
is handed no file.  Offline: a fake adapter that takes the file the way every adapter does,
then the real adapters with a `python3` that refuses the tool.
"""

import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch

MARK = "the rules acme was launched with"
REFUSING = """#!/bin/sh
case "$1" in */tools/rulebook.py) echo "the rulebook tool was run" >&2; exit 97 ;; esac
exec {python} "$@"
"""
ADAPTER = f'''#!/bin/sh
[ "$1" = interactive ] || exit 97
[ "${{5:-}}" = new ] && [ -n "${{AK_TEST_CANNOT_PIN:-}}" ] && exit 3
printf '%s\\n' "${{AGENTKIT_RULEBOOK:-none}}" >>"$AK_TEST_HANDED"
rb=${{AGENTKIT_RULEBOOK:-$(python3 "{REPO}/tools/rulebook.py" "$AGENTKIT_SESSION")}} || exit 2
echo "fake-tui --rules $rb"
'''


class LaunchWritesItsRulebook(Sandbox):
    def setUp(self):
        super().setUp()
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "claude.sh").write_text(ADAPTER)
        (adapters / "claude.sh").chmod(0o755)
        self.handed = self.root / "handed"
        self.stack.enter_context(patch.dict(os.environ, {
            config.ADAPTER_DIR_ENV: str(adapters), "AK_TEST_HANDED": str(self.handed)}))

    def test_the_adapter_is_handed_the_file_the_launch_wrote(self):
        cmd, conversation = orch.fresh_command(self.cfg, "opus", seat="acme")
        self.assertTrue(conversation)
        named = Path(cmd[cmd.index("--rules") + 1])
        self.assertEqual(named, config.rulebook_path("acme"))
        self.assertEqual(named.read_text(), config.seat_rulebook("acme"))
        # written before the adapter was asked, and the tool named that file
        self.assertEqual(self.handed.read_text().split(), [str(named)])

    def test_a_harness_asked_twice_gets_one_writing(self):
        # one that cannot be told a conversation id is asked again without one
        with patch.dict(os.environ, {"AK_TEST_CANNOT_PIN": "1"}), \
                patch.object(orch, "write_rulebook", wraps=orch.write_rulebook) as wrote:
            cmd, conversation = orch.fresh_command(self.cfg, "opus", seat="acme")
        self.assertIsNone(conversation)
        self.assertEqual(wrote.call_count, 1)
        self.assertEqual(self.handed.read_text().split(), [cmd[cmd.index("--rules") + 1]])



class EveryAdapterTakesIt(Sandbox):
    """The real adapters, by their manifests, so one added later is held to it too."""

    def test_handed_a_rulebook_no_adapter_runs_the_tool(self):
        handed = self.root / "handed.md"
        handed.write_text(MARK + "\n")
        refusing = self.root / "bin"
        refusing.mkdir()
        (refusing / "python3").write_text(REFUSING.format(python=shutil.which("python3")))
        (refusing / "python3").chmod(0o755)
        # the usual login: a seat this runs from may be on another, which OpenCode has none of
        env = {**{key: value for key, value in os.environ.items() if key != "AGENTKIT_ACCOUNT"},
               config.SESSION_ENV: "acme", config.RULEBOOK_ENV: str(handed),
               "PATH": os.pathsep.join([str(refusing), os.environ["PATH"]])}
        for harness in sorted(path.stem for path in (REPO / "adapters").glob("*.toml")):
            with self.subTest(harness=harness):
                line = subprocess.run([str(REPO / f"adapters/{harness}.sh"), "interactive",
                                       "test-model", "high"], env=env, capture_output=True,
                                      text=True, timeout=60)
                self.assertEqual(line.returncode, 0, line.stderr)
                # the file itself, its text, or a copy the adapter made for its harness
                copies = [path for path in Path.home().rglob("*")
                          if path.is_file() and MARK in path.read_text(errors="replace")]
                self.assertTrue(str(handed) in line.stdout or MARK in line.stdout or copies,
                                line.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
