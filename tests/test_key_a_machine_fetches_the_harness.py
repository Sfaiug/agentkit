"""The first turn on a machine fetches the harness program at the version this host runs, for the
machine's `uname -m`, whole or not at all, and a later turn fetches nothing. A fetch that fails, a
toml that says nothing of where to fetch and a version that cannot be read each leave the turn here.

Black-box, as tests/test_key_a_turn_runs_on_a_machine.py is, on its machine, with a fake `curl` that
logs each URL and serves a stand-in program as the real ones come: claude a plain file, codex a
`.tar.gz` holding it under another name. Each stand-in, run, says its name.
"""

import io
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

CLAUDE = ("https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/"
          "claude-code-releases/1.2.3/linux-{}/claude")
CODEX = ("https://github.com/openai/codex/releases/download/rust-v4.5.6/"
         "codex-{}-unknown-linux-musl.tar.gz")
VERSIONS = {"claude": "1.2.3 (Claude Code)", "codex": "codex-cli 4.5.6"}
# What curl does once it has logged `$url`: `{tarball}` is codex's download, `{gate}` a file to
# wait for.
SERVES = 'case "$url" in *.tar.gz) cat {tarball} ;; *) printf "#!/bin/sh\\necho claude\\n" ;; esac'
FAILS = "echo half a program; exit 22"


def turn(program, step):
    """`step`, writing where it ran and what the harness program there says."""
    return {"sh": 'echo "${container:-here}" >"${AK_HAND_IN%/*}/where"; '
                  f'{program} >"${{AK_HAND_IN%/*}}/said"', **step}


class AMachineFetchesTheHarness(unittest.TestCase):
    def machine(self, arch, serves, versions=VERSIONS):
        """(home, machine, its URL log), `arch` its `uname -m` and `serves` what its curl does."""
        home = Home()
        self.addCleanup(home.close)
        machine = akmachine.install(home)
        for harness, version in versions.items():
            home.fake(harness, f"#!/bin/sh\necho {shlex.quote(version)}\n")
        with tarfile.open(machine / "codex.tar.gz", "w:gz") as tar:
            data = b"#!/bin/sh\necho codex\n"
            info = tarfile.TarInfo(f"codex-{arch}-unknown-linux-musl")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        urls = machine / "urls"
        (machine / "bin/curl").write_text(
            f'#!/bin/bash\nurl=${{@: -1}}\necho "$url" >>{urls}\n'
            + serves.format(tarball=machine / "codex.tar.gz", gate=machine / "gate") + "\n")
        (machine / "bin/uname").write_text(
            f'#!/bin/sh\n[ "$1" != -m ] && echo Linux || echo {arch}\n')
        (machine / "bin/uname").chmod(0o755)
        return home, machine, urls

    def fetched(self, urls):
        return sorted(urls.read_text().split()) if urls.exists() else []

    def programs(self, machine):
        """Every file under the machine's harness programs, but the locks."""
        root = machine / "home/.agentkit-helper/harness"
        return sorted(str(path.relative_to(root)) for path in root.rglob("*")
                      if path.is_file() and path.suffix != ".lock")

    def run_task(self, home, models=("opus", "astra"), no_fetch=()):
        """(where the task's turns ran, what the program said in each) once it passed: opus's first
        turn writes, and with no other model about it reviews too."""
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, list(models),
                       settings={"suite_helper": "acme-linux", "machine_turns": True})
        fakes = fakeadapter.install(home, claude=[turn("claude", fakeadapter.WORK),
                                                  turn("claude", fakeadapter.PASS)],
                                    codex=turn("codex", fakeadapter.PASS))
        for harness in no_fetch:
            text = fakes[harness].manifest.read_text()
            fakes[harness].manifest.write_text(re.sub(r"(?ms)^\[fetch\]\n.*?(?=^\[|\Z)", "", text))
        done = home.ak("run", str(taskfile.write(home, rig.path)), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(home)
        state = json.loads((run / "run.json").read_text())
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        return (sorted(path.read_text().strip() for path in run.rglob("where")),
                sorted(path.read_text().strip() for path in run.rglob("said")))

    def test_the_first_turn_fetches_this_hosts_version_for_the_machine(self):
        for arch, claude, codex in (("aarch64", "arm64", "aarch64"), ("x86_64", "x64", "x86_64")):
            with self.subTest(arch=arch):
                home, machine, urls = self.machine(arch, SERVES)
                self.assertEqual(self.run_task(home), (["docker"] * 2, ["claude", "codex"]))
                self.assertEqual(self.fetched(urls),
                                 sorted([CLAUDE.format(claude), CODEX.format(codex)]))
                self.assertEqual(self.programs(machine),
                                 ["claude/1.2.3/claude", "codex/4.5.6/codex"])

    def test_the_second_turn_fetches_nothing(self):
        home, machine, urls = self.machine("x86_64", SERVES)
        self.assertEqual(self.run_task(home, ["opus"]), (["docker"] * 2, ["claude"] * 2))
        self.assertEqual(self.fetched(urls), [CLAUDE.format("x64")])

    def test_a_fetch_that_fails_leaves_the_turn_here_and_no_program(self):
        home, machine, urls = self.machine("x86_64", FAILS)
        self.assertEqual(self.run_task(home)[0], ["here"] * 2)
        self.assertEqual(self.fetched(urls), sorted([CLAUDE.format("x64"), CODEX.format("x86_64")]))
        self.assertEqual(self.programs(machine), [])

    def test_a_machine_of_a_kind_the_toml_does_not_name_fetches_nothing(self):
        home, machine, urls = self.machine("riscv64", SERVES)
        self.assertEqual(self.run_task(home)[0], ["here"] * 2)
        self.assertEqual((self.fetched(urls), self.programs(machine)), ([], []))

    def test_no_table_or_no_version_runs_here_and_fetches_nothing(self):
        home, machine, urls = self.machine("x86_64", SERVES, {"claude": VERSIONS["claude"]})
        home.fake("codex", "#!/bin/sh\nexit 1\n")    # a version that cannot be read
        self.assertEqual(self.run_task(home, no_fetch=["claude"])[0], ["here"] * 2)
        self.assertEqual((self.fetched(urls), self.programs(machine)), ([], []))

    def test_turns_at_once_wait_for_one_fetch(self):
        home, machine, urls = self.machine(
            "x86_64", f"until [ -e {{gate}} ]; do sleep 0.1; done; {SERVES}")
        locks = machine / "locks"
        (machine / "bin/flock").write_text(
            f'#!/bin/bash\necho "$1" >>{locks}\nexec {shutil.which("flock")} "$@"\n')
        (machine / "bin/flock").chmod(0o755)
        parcel = io.BytesIO()
        with tarfile.open(fileobj=parcel, mode="w") as tar:
            for name, text in (("image/Containerfile", "FROM acme\n"),
                               ("harness", "claude/1.2.3/claude"),
                               ("fetch/x86_64", CLAUDE.format("x64"))):
                info = tarfile.TarInfo(name)
                info.size = len(text)
                tar.addfile(info, io.BytesIO(text.encode()))
        tools = Path(akmachine.__file__).resolve().parents[2] / "tools/helper"
        script = (tools / "linux.sh").read_text() + (tools / "mac.sh").read_text()
        turns = [subprocess.Popen(
            [home.bin / "ssh", "acme-linux",
             shlex.join(["bash", "-c", script, "mac.sh", "prepare", key, "acme:1", "repo"])],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for key in ("one", "two")]
        for each in turns:
            self.addCleanup(each.kill)
            each.stdin.write(parcel.getvalue())
            each.stdin.close()
        # The first's download ends once both have asked for its lock; with no lock, none asks.
        deadline = time.monotonic() + 120
        while (not locks.exists() or locks.read_text().count("1.2.3.lock\n") < 2) \
                and time.monotonic() < deadline:
            time.sleep(0.1)
        (machine / "gate").touch()
        self.assertEqual([each.wait(timeout=120) for each in turns], [3, 3])    # 3: no history sent
        self.assertEqual(self.fetched(urls), [CLAUDE.format("x64")])
        self.assertEqual(self.programs(machine), ["claude/1.2.3/claude"])


if __name__ == "__main__":
    unittest.main()
