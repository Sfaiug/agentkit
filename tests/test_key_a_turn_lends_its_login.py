"""A model turn on a machine reads a copy of its account's login, sent over ssh's stdin and gone
from the machine before `collect` can send anything; a login that lapses within the hour or cannot
be lent keeps the turn here; and a turn starting holds two of the machine's CPUs, not half of it.

Black-box, as tests/test_key_a_turn_runs_on_a_machine.py, on its machine, with its fake adapters,
whose `lend` is the real tools/lend.py. ssh and docker log their arguments, and ssh what the HOME
of any parcel on the machine holds at each `collect` and `finish`, while the turn's stand-in harness
says where it ran, which account's login it read and its environment, and leaves a file of its own.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "helper"
TOKEN = "fixture-token"
HERE = '"${AK_HAND_IN%/*}"'
READS = (f'echo "${{container:-here}}" >{HERE}/where; env >{HERE}/env; echo mine >"$HOME/own.txt"; '
         f"grep -o 'for-[a-z]*' \"$HOME/{fakeadapter.LENT}\" >{HERE}/login")
EXECUTE = {"sh": READS, "write": {"retry.txt": "hello\n"}, "final": "## Summary\nedited",
           "hand_in": [["done"]]}
REVIEW = {"sh": READS, "final": "Handed in.", "hand_in": [["done"]]}

SSH = r"""#!/bin/bash
printf '%s\n' "$*" >>"{log}"
case ${{@: -1}} in *" mac.sh collect "*|*" mac.sh finish "*)
  find "{tree}" -path "{tree}/*/home/*" -type f 2>/dev/null >>"{seen}" ;;
esac
exec "{real}" "$@"
"""
# The first turn's container does not start, and as that turn prepares, holding what it holds until
# it starts, two suites ask to come in, and leave again.
DOCKER = r"""#!/bin/bash
printf '%s\n' "$*" >>"{log}"
case "$1 $5" in "run "*-turn) [ -e "{refused}" ] || {{ : >"{refused}"; exit 125; }} ;; esac
if [ "$1 $2" = "image inspect" ] && [ ! -e "{asked}" ] &&
    ls "{tree}"/*/harness >/dev/null 2>&1; then
  for key in first second; do
    bash -c "$(cat "{tools}/linux.sh" "{tools}/mac.sh")" mac.sh prepare "$key" ak-helper-suite:0 \
      suite </dev/null >/dev/null 2>&1
    echo "$?" >>"{asked}"
  done
  rm -rf "{tree}/first" "{tree}/second"
fi
exec "$0.real" "$@"
"""


class ATurnLendsItsLogin(unittest.TestCase):
    def run_task(self, lend=None):
        """The finished run's directory, and the machine with its logs."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"],
                       providers={"anthropic": {"mode": "subscription", "accounts": ["second"]}},
                       settings={"suite_helper": "acme-linux", "machine_turns": True})
        fakes = fakeadapter.install(home, claude=EXECUTE, codex=REVIEW)
        for fake in fakes.values():
            if lend:
                fake.answer("lend", *lend)
        machine = akmachine.install(home)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        (machine / "bin/nproc").write_text("#!/bin/sh\necho 4\n")    # eight CPUs to give
        paths = {"log": machine / "args.log", "seen": machine / "seen.log",
                 "refused": machine / "refused", "asked": machine / "asked", "tools": TOOLS,
                 "tree": machine / "home/.agentkit-helper"}
        for path in paths["log"], paths["seen"]:
            path.touch()
        real = home.bin / "ssh.real"
        (home.bin / "ssh").rename(real)
        home.fake("ssh", SSH.format(real=real, **paths))
        (machine / "bin/docker").rename(machine / "bin/docker.real")
        (machine / "bin/docker").write_text(DOCKER.format(**paths))
        (machine / "bin/docker").chmod(0o755)
        task = taskfile.write(home, rig.path)
        done = home.ak("run", str(task), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(home)
        state = json.loads((run / "run.json").read_text())
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        return run, machine

    def said(self, run, name):
        return sorted(path.read_text().strip() for path in run.rglob(name))

    def test_the_turn_reads_its_account_s_login_and_the_machine_keeps_none(self):
        run, machine = self.run_task()
        self.assertEqual(self.said(run, "where"), ["docker"] * 2)
        self.assertEqual(self.said(run, "login"), ["for-second", "for-usual"])
        # A turn's two CPUs and a suite's four leave the quarter another suite needs.
        asked = (machine / "asked").read_text().split()
        self.assertEqual(len(asked), 2, asked)
        self.assertNotIn("252", asked)
        turn = next(line for line in (machine / "args.log").read_text().splitlines()
                    if line.startswith("run ") and "-turn " in line)
        self.assertIn("--memory 4096m", turn)
        # never on a command line, in the turn's environment, or back here
        self.assertNotIn(TOKEN, (machine / "args.log").read_text())
        for path in run.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes(), path)
        for env in run.rglob("env"):
            self.assertNotIn("AGENTKIT_ACCOUNT=", env.read_text())
        # gone at each `collect` and `finish`, the failed container's too, a model's own file there
        self.assertTrue((machine / "refused").exists())
        seen = {Path(line).name for line in (machine / "seen.log").read_text().splitlines()}
        self.assertEqual(seen, {".gitconfig", "own.txt"})
        self.assertEqual([*machine.rglob(Path(fakeadapter.LENT).name)], [])
        # `finish` removed every parcel, which no directory made as root would survive
        tree = machine / "home/.agentkit-helper"
        self.assertEqual([path.name for path in tree.iterdir()
                          if path.is_dir() and path.name not in ("harness", "mirrors")], [])

    def test_a_login_that_lapses_within_the_hour_or_cannot_be_lent_keeps_the_turn_here(self):
        for lend in ((str(int(time.time()) + 1800),), ("", 1)):
            with self.subTest(lend=lend):
                run, machine = self.run_task(lend=lend)
                self.assertEqual(self.said(run, "where"), ["here"] * 2)
                self.assertEqual([*machine.glob("docker/roots/*-turn")], [])
                # no parcel with a HOME, a turn's, ever reached the machine
                self.assertEqual((machine / "seen.log").read_text(), "")


if __name__ == "__main__":
    unittest.main()
