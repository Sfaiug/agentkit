"""A turn's conversation travels with it: what a turn on a machine wrote at its harness's `sessions`
comes home under the id it reported, and a resumed turn's parcel holds what this host has there.

Black-box, as tests/test_key_a_turn_runs_on_a_machine.py is, on its machine: each harness stand-in
writes its conversation under its HOME where its shipped manifest says, and `where` in its out dir.
"""

import json
import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

WHERE = 'echo "${container:-here}" >"${AK_HAND_IN%/*}/where"; '
CLAUDE = ".claude/projects/acme/sid-1"
CODEX = ".codex/sessions/2026/10/30/rollout-rev-1.jsonl"
# What the machine's tar sends them as: names that start at the conversation and climb out of HOME,
# or whose `.` or empty part matches a glob's `*` where a path drops it.
CLIMBS = ('#!/bin/sh\nexec {tar} -P --transform "s,/sid-1/climbs,/sid-1/../../../../climbed,;'
          's,/acme/sid-1/dot,/./sid-1-dot,;s,/acme/sid-1/empty,//sid-1-empty," "$@"\n')


def adds(path, line, *lines_before):
    """A step's `sh`: `line` added to the file `path` under HOME, once it holds `lines_before`."""
    held = "".join(f'grep -qx {before} "$HOME/{path}" && ' for before in lines_before)
    return (f'mkdir -p "$(dirname "$HOME/{path}")" && {held}echo {line} >>"$HOME/{path}"; ')


# Outside the globs: beside its folders, in its folder but under another id or too shallow, a `..`
# that lands there too, a link at a glob's place, and a folder this host holds as a link.
ELSEWHERE = ('echo x >"$HOME/elsewhere-sid-1.jsonl"; echo x >"$HOME/.claude/settings.json"; '
             f'echo x >"$HOME/{CLAUDE}/../other.jsonl"; '
             f'echo x >"$HOME/{CLAUDE}/../../sid-1-shallow.jsonl"; '
             f'echo x >"$HOME/{CLAUDE}/tools/../../../sid-1-up.jsonl"; '
             f'ln -s "$HOME/.gitconfig" "$HOME/{CLAUDE}-link"; echo x >"$HOME/{CLAUDE}/climbs"; '
             f'echo x >"$HOME/{CLAUDE}/dot"; echo x >"$HOME/{CLAUDE}/empty"; '
             f'mkdir "$HOME/{CLAUDE}/linked"; echo x >"$HOME/{CLAUDE}/linked/key"; ')


class ATurnCarriesItsConversation(unittest.TestCase):
    def ready(self, claude, codex):
        """The Home, each harness's stand-in, its machine and the rig, a task yet to run there."""
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"],
                       settings={"suite_helper": "acme-linux", "machine_turns": True})
        fakes = fakeadapter.install(home, claude=claude, codex=codex)
        machine = akmachine.install(home)
        for harness in fakes:    # each fake adapter's program, which it never runs
            place = machine / "home/.agentkit-helper/harness" / harness
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        return home, fakes, machine, rig

    def finish(self, home, rig):
        """The task runs and passes."""
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual(state["state"], "pass")

    def where(self, fake):
        return [Path(run["argv"][4], "where").read_text().strip() for run in fake.runs()]

    def test_it_comes_home_and_goes_back_and_nothing_else_comes(self):
        first = {**fakeadapter.WORK, "session": "sid-1",
                 "sh": WHERE + adds(f"{CLAUDE}.jsonl", "first")
                 + adds(f"{CLAUDE}/tools/part", "tool") + ELSEWHERE}
        second = {**fakeadapter.DISPUTE, "sh": WHERE + adds(f"{CLAUDE}.jsonl", "second", "first")}
        review = {**fakeadapter.FAIL, "session": "rev-1", "sh": WHERE + adds(CODEX, "found")}
        again = {**fakeadapter.PASS, "sh": WHERE + adds(CODEX, "passed", "found")}
        home, fakes, machine, rig = self.ready([first, second], [review, again])
        tar = machine / "bin/tar"
        tar.write_text(CLIMBS.format(tar=shutil.which("tar")))
        tar.chmod(0o755)
        outside = home.root / "outside"
        outside.mkdir()
        (home.path / CLAUDE).mkdir(parents=True)
        (home.path / CLAUDE / "linked").symlink_to(outside)
        before = self.files(home)
        self.finish(home, rig)

        self.assertEqual(self.where(fakes["claude"]), ["docker", "docker"])
        self.assertEqual(self.where(fakes["codex"]), ["docker", "docker"])
        self.assertEqual(fakes["claude"].runs()[1]["argv"][-1], "sid-1")
        self.assertEqual(fakes["codex"].runs()[1]["argv"][-1], "rev-1")
        self.assertEqual((home.path / f"{CLAUDE}.jsonl").read_text(), "first\nsecond\n")
        self.assertEqual((home.path / CODEX).read_text(), "found\npassed\n")
        self.assertEqual(self.files(home) - before,
                         {f"{CLAUDE}.jsonl", f"{CLAUDE}/tools/part", CODEX})
        self.assertEqual([*outside.iterdir()], [])

    def test_a_conversation_this_host_does_not_hold_resumes_here(self):
        # The second id's `/` would reach a file deeper than the glob's place, which is no
        # conversation of that name, as one with a `..` would reach out of the folder.
        for sid in ("sid-gone", "deep/other"):
            with self.subTest(sid=sid):
                work = {**fakeadapter.WORK, "sh": WHERE, "session": sid}
                home, fakes, _, rig = self.ready(
                    [work, {**fakeadapter.DISPUTE, "sh": WHERE}],
                    [{**fakeadapter.FAIL, "sh": WHERE}, {**fakeadapter.PASS, "sh": WHERE}])
                home.write(".claude/projects/acme/deep/other.jsonl", "other\n")
                self.finish(home, rig)
                self.assertEqual(self.where(fakes["claude"]), ["docker", "here"])
                self.assertEqual(fakes["claude"].runs()[1]["argv"][-1], sid)

    def test_a_harness_with_no_sessions_runs_here(self):
        home, fakes, _, rig = self.ready({**fakeadapter.WORK, "sh": WHERE},
                                         {**fakeadapter.PASS, "sh": WHERE})
        manifest = fakes["codex"].manifest
        manifest.write_text("".join(line for line in manifest.read_text().splitlines(True)
                                    if not line.startswith("sessions")))
        self.finish(home, rig)
        self.assertEqual(self.where(fakes["claude"]), ["docker"])
        self.assertEqual(self.where(fakes["codex"]), ["here"])

    def files(self, home):
        """Each file or link under HOME by its name there, but ak's state and the checkouts."""
        found = {str(Path(root, name).relative_to(home.path))
                 for root, _, names in os.walk(home.path) for name in names}
        return {name for name in found if not name.startswith((".agentkit/", "code/"))}


if __name__ == "__main__":
    unittest.main()
