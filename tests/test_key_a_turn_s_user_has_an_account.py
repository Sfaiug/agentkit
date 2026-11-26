"""On a Linux machine `build` hands every recipe the machine's user and group ids as `AK_UID` and
`AK_GID`, and ak's own recipe (`tools/helper/Containerfile`) makes `ak` and its group with them,
defaulting to 1000 when unset or when the base image already has an account or group with that id.

Black-box, on the machine of tests/fixtures/akmachine.py whose `id` answers 1001 and 1002; ak's
recipe is read as text and its `RUN` that makes `ak` is run against fake `getent`, `groupadd` and
`useradd`.
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

WHERE = 'echo "${container:-here}" >"${AK_HAND_IN%/*}/where"'
EXECUTE = {"sh": WHERE, "write": {"done.txt": "ok\n"}, "final": "## Summary\nedited",
           "hand_in": [["done"]]}
REVIEW = {"sh": WHERE, "final": "Handed in.", "hand_in": [["done"]]}

# Fake `id` on a Linux machine whose user is 1001 and group is 1002.
FAKE_ID = '#!/bin/sh\ncase "$*" in -u) echo 1001 ;; -g) echo 1002 ;; *) exec /usr/bin/id "$@" ;; esac\n'

# Fake base-image account tools: root (0:0) and users (:100) already exist.
FAKE_GETENT = (
    '#!/bin/sh\n'
    'case "$1 $2" in "passwd 0"|"group 0"|"group 100") exit 0 ;; *) exit 2 ;; esac\n'
)
RECORD = '#!/bin/sh\nprintf "%s\\n" "$0 $*" >>"$OUT"\n'


def recipe_instructions(text):
    """Logical Dockerfile instructions (joined continuations, comments dropped)."""
    joined = re.sub(r"\\\n[ \t]*", " ", text)
    return [line.strip() for line in joined.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


class ATurnSUserHasAnAccount(unittest.TestCase):
    def test_linux_build_passes_the_machine_s_user_and_group_ids(self):
        home = Home()
        self.addCleanup(home.close)
        # A recipe that declares neither argument still builds with both passed.
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\nhealth: none\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"],
                       settings={"suite_helper": "acme-linux", "turns_on_machines": True})
        fakeadapter.install(home, claude=EXECUTE, codex=REVIEW)
        machine = akmachine.install(home)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        (machine / "bin/id").write_text(FAKE_ID)
        (machine / "bin/id").chmod(0o755)
        task = taskfile.write(home, rig.path, done_when=("test -f done.txt",))
        done = home.ak("run", str(task), env={"AK_HOST_READINGS": akmachine.CROWDED}, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(home)
        state = json.loads((run / "run.json").read_text())
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        self.assertEqual([path.read_text().strip() for path in run.rglob("where")], ["docker"] * 2)
        built = [*machine.glob("docker/images/*")]
        self.assertEqual(len(built), 1, built)
        self.assertEqual(json.loads(built[0].read_text()), {"AK_UID": "1001", "AK_GID": "1002"})

    def test_ak_s_recipe_makes_ak_from_ak_uid_and_ak_gid_defaulting_to_1000(self):
        text = (REPO / "tools/helper/Containerfile").read_text()
        opening = "\n".join(line for line in text.splitlines()
                            if line.startswith("#") and text.index(line) < text.index("FROM "))
        self.assertIn("AK_UID", opening)
        self.assertIn("AK_GID", opening)
        instructions = recipe_instructions(text)
        from_index = next(i for i, line in enumerate(instructions) if line.startswith("FROM "))
        after_from = instructions[from_index + 1:]
        self.assertIn("ARG AK_UID=1000", after_from)
        self.assertIn("ARG AK_GID=1000", after_from)
        self.assertEqual(after_from[-1], "USER ak")
        make_ak = next((line[4:] for line in after_from
                        if line.startswith("RUN ") and "useradd" in line), None)
        self.assertIsNotNone(make_ak, after_from)

        with tempfile.TemporaryDirectory(prefix="ak-test-recipe-") as root:
            tools = Path(root) / "bin"
            tools.mkdir()
            for name, body in (("getent", FAKE_GETENT), ("groupadd", RECORD), ("useradd", RECORD)):
                (tools / name).write_text(body)
                (tools / name).chmod(0o755)
            out = Path(root) / "calls"
            cases = (
                ({"AK_UID": "1001", "AK_GID": "1002"}, "1001", "1002"),
                ({"AK_UID": "1000", "AK_GID": "1000"}, "1000", "1000"),
                ({}, "1000", "1000"),
                ({"AK_UID": "", "AK_GID": ""}, "1000", "1000"),
                ({"AK_UID": "0", "AK_GID": "0"}, "1000", "1000"),
                ({"AK_UID": "1001", "AK_GID": "100"}, "1001", "1000"),
                ({"AK_UID": "0", "AK_GID": "1001"}, "1000", "1001"),
            )
            for given, want_uid, want_gid in cases:
                with self.subTest(given=given):
                    out.unlink(missing_ok=True)
                    env = {"PATH": f"{tools}:/usr/bin:/bin", "OUT": str(out), **given}
                    ran = subprocess.run(["/bin/sh", "-c", make_ak], env=env,
                                         capture_output=True, text=True)
                    self.assertEqual(ran.returncode, 0, ran.stderr)
                    calls = [line.split() for line in out.read_text().splitlines()]
                    self.assertEqual(
                        [[Path(call[0]).name, *call[1:]] for call in calls],
                        [["groupadd", "-g", want_gid, "ak"],
                         ["useradd", "-m", "-u", want_uid, "-g", want_gid, "-s", "/bin/bash", "ak"]],
                    )

    def test_mac_helper_passes_neither_build_arg(self):
        mac = (REPO / "tools/helper/mac.sh").read_text()
        self.assertNotIn("AK_UID", mac)
        self.assertNotIn("AK_GID", mac)


if __name__ == "__main__":
    unittest.main()
