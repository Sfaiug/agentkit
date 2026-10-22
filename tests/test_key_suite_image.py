"""`suite_image:` in a repository's AGENTS.md names the recipe its suite's pieces are built from
on the suite helper; a recipe ak cannot send leaves the suite here.

A suite that names AK_SHARD may run its pieces on a Mac (`suite_helper` in config.toml), each
in a Linux VM built from a recipe: the file `suite_image:` names, over the repository's own
tools/helper/Containerfile.  ak sends the Mac that recipe as the image's Containerfile with each
file it COPYs, their modes kept, under a tag carrying their hash, so a changed recipe builds a
new image for the same repository.  A recipe HEAD does not track, or one copying anything but
tracked files named by plain path, cannot be sent: the Mac is never asked, a WARN line says
why, and the suite runs here.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, against the bare origin of gitrig.py and the GitHub of fakegh.py,
with scripted harnesses from fakeadapter.py; the Mac is an `ssh` of the test's answering
tools/helper/mac.sh's verbs, which keeps each parcel it is sent and then fails to take the
suite, so every suite runs here and lands.
"""

import json
import sys
import tarfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

SUITE = 'test -n "$AK_SHARD"'
RECIPE = "FROM docker.io/library/debian:trixie-slim\nCOPY tools/setup.sh /opt/setup.sh\n"
SETUP = "#!/bin/sh\necho ready\n"
DEFAULT = "FROM docker.io/library/alpine:3.20\n"
GLOB = "COPY tools/*.sh /opt/"
NOTES = {"write": {"notes.txt": "notes\n"}, "commit": "add notes.txt",
         "final": "## Summary\nwrote notes.txt", "hand_in": [["done"]]}
# The Mac: room for every piece, no history kept yet; it keeps each parcel by the suite's key,
# then exits as ssh does when the connection breaks.
SSH = """
import json, shlex, sys
words = shlex.split(" ".join(sys.argv[1:]))
verb, *args = words[words.index("mac.sh") + 1:]
with open(KEPT + "/calls.jsonl", "a") as log:
    log.write(json.dumps([verb, *args[:3]]) + "\\n")
if verb == "probe":
    print("cpus 64\\nload 0\\nmemory_mb 1048576\\nfree_percent 100")
elif verb == "prepare":
    open(f"{KEPT}/{args[0]}.tar", "wb").write(sys.stdin.buffer.read())
    sys.exit(255)
"""


def front(image):
    return f"---\ntests: {SUITE}\nsuite_image: {image}\n---\n# widgets\n"


def staged(case, files):
    """A Home whose config names the Mac, and the repository with `files` on main."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    case.kept = home.root / "mac"
    case.kept.mkdir()
    home.fake("ssh", f"#!{sys.executable}\nKEPT = {str(case.kept)!r}\n{SSH}")
    case.rig = Rig(home, "widgets", files=files)
    GitHub(home).grant(case.rig.slug, "WRITE")
    akconfig.write(home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
    fakeadapter.install(home, claude=["work", NOTES], codex="pass")


def landed(case, title, done_when):
    """Run a task to the end, and its record."""
    task = taskfile.write(case.home, case.rig.path, title, done_when=(done_when,))
    done = case.home.ak("run", str(task), timeout=300)
    states = [json.loads((run / "run.json").read_text()) for run in taskfile.runs(case.home)]
    return done, next(state for state in states if state["title"] == title)


def asked(case):
    """Each verb the Mac was asked, with its first arguments."""
    calls = case.kept / "calls.jsonl"
    return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


class SentToTheMac(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        staged(cls, {"AGENTS.md": front("images/suite.Containerfile"),
                     "images/suite.Containerfile": RECIPE, "tools/setup.sh": SETUP,
                     "tools/helper/Containerfile": DEFAULT})
        (cls.rig.path / "tools/setup.sh").chmod(0o755)
        cls.rig.commit({}, "Make setup executable")
        cls.first = landed(cls, "Add retry file", "test -f retry.txt")
        cls.first_asked = asked(cls)
        cls.rig.git("pull", "-q")
        cls.rig.commit({"images/suite.Containerfile": RECIPE + "RUN sh /opt/setup.sh\n"})
        cls.second = landed(cls, "Add notes file", "test -f notes.txt")
        cls.second_asked = asked(cls)[len(cls.first_asked):]

    def prepared(self, calls):
        """(image, repository) of each parcel the Mac was sent."""
        return [tuple(args[1:3]) for verb, *args in calls if verb == "prepare"]

    def test_the_mac_is_sent_the_named_recipe_with_each_file_it_copies(self):
        key = next(args[0] for verb, *args in self.first_asked if verb == "prepare")
        with tarfile.open(self.kept / f"{key}.tar") as parcel:
            recipe = parcel.extractfile("image/Containerfile").read().decode()
            copied = parcel.getmember("context/tools/setup.sh")
            self.assertEqual(parcel.extractfile(copied).read().decode(), SETUP)
            sent = [parcel.extractfile(m).read() for m in parcel.getmembers() if m.isfile()]
        self.assertEqual(recipe, RECIPE)
        self.assertEqual(copied.mode & 0o777, 0o755)
        self.assertNotIn(DEFAULT.encode(), sent)

    def test_a_changed_recipe_is_a_new_image_of_the_same_repository(self):
        first, second = set(self.prepared(self.first_asked)), set(self.prepared(self.second_asked))
        self.assertEqual((len(first), len(second)), (1, 1), (first, second))
        (image, repo), (again, same) = first.pop(), second.pop()
        self.assertEqual(same, repo)
        self.assertNotEqual(again, image)
        for tag in (image, again):
            self.assertRegex(tag, rf"^ak-helper-{repo}:[0-9a-f]+$")

    def test_a_suite_the_mac_did_not_take_runs_here_and_lands(self):
        for done, state in (self.first, self.second):
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual((state["state"], state["merged"]), ("pass", True))
            self.assertEqual({key: state["final_check"][key] for key in ("outcome", "where")},
                             {"outcome": "passed", "where": "landing"})


class NotSent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        staged(cls, {"AGENTS.md": front("images/gone.Containerfile"), "tools/setup.sh": SETUP})
        cls.untracked = landed(cls, "Add retry file", "test -f retry.txt")
        cls.untracked_asked = asked(cls)
        cls.rig.git("pull", "-q")
        cls.rig.commit({"AGENTS.md": front("images/glob.Containerfile"),
                        "images/glob.Containerfile": f"FROM scratch\n{GLOB}\n"})
        cls.globbed = landed(cls, "Add notes file", "test -f notes.txt")
        cls.globbed_asked = asked(cls)

    def warned(self, needle):
        """Whether a WARN line naming `needle` was written under the runs directory."""
        return any("WARN" in line and needle in line
                   for path in (self.home.path / ".agentkit/runs").rglob("*") if path.is_file()
                   for line in path.read_text(errors="replace").splitlines())

    def test_a_recipe_head_does_not_track_is_never_sent_and_the_suite_runs_here(self):
        done, state = self.untracked
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        self.assertEqual(self.untracked_asked, [])
        self.assertTrue(self.warned("images/gone.Containerfile"))

    def test_a_recipe_copying_anything_but_tracked_files_is_never_sent(self):
        done, state = self.globbed
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        self.assertEqual(self.globbed_asked, [])
        self.assertTrue(self.warned(GLOB))


if __name__ == "__main__":
    unittest.main()
