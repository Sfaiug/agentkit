"""An `ak worker` turn's commands reach no credential of the host it runs on.

A turn runs code a model chose, so its box passes on no GitHub token variable or SSH agent
address, and every credential file and folder of the account reads empty inside it: GitHub's
logins, Git's stores and caches (the default ones, those the environment names and one a
credential helper names), SSH keys, keys linked into `~/.ssh` and the agent's socket, each
through a link too.  So does a file or folder the harness reads on its own, under its
manifest's `[instructions] unswitched`.  A `~/.ssh` that loops or is a file stops no turn.  ak
asks Git which stores to hide with no token in its environment, and asks its own Git, never
one the workspace puts on PATH.  The turn's workspace here is HOME itself, so only the box
hides what is planted there.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, its harness the scripted adapter of fakeadapter.py, whose `sh` step
probes from inside the turn and writes what it found to `seen.json` in the workspace.
"""

import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import SYSTEM, Home, boxable

TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
SECRET = "fixture-secret\n"
# What the turn reads at each path given, its listing for a folder, "" for nothing readable;
# the variables it was given; and whether `agent.sock` in its workspace answers.
PROBE = r"""
import json, os, socket, sys

def held(path):
    try:
        return sorted(os.listdir(path)) if os.path.isdir(path) else open(path).read()
    except OSError:
        return ""

with socket.socket(socket.AF_UNIX) as agent:
    answers = agent.connect_ex("agent.sock") == 0
with open("seen.json", "w") as seen:
    json.dump({"paths": {path: held(path) for path in sys.argv[1:]},
               "env": {key: os.environ.get(key) for key in (*TOKENS, "SSH_AUTH_SOCK")},
               "agent": answers}, seen)
""".replace("TOKENS", repr(TOKENS))
GIT = shutil.which("git", path=os.pathsep.join(SYSTEM))


@unittest.skipUnless(boxable() and GIT, "needs git and a bwrap able to box a turn")
class AWorkerTurnReachesNoCredential(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {"beta": {"harness": "acme", "model": "beta-1",
                                            "effort": "low"}})
        self.fake = fakeadapter.install(self.home, acme="pass")["acme"]
        with self.fake.manifest.open("a") as manifest:
            manifest.write('\n[instructions]\nunswitched = ["~/.acme/AGENTS.md", "~/.acme/rules"]\n')
        self.task = self.home.write("tasks/fix-api.md", "Fix the api.\n")
        self.planted = []

    def plant(self, relative, text=SECRET):
        path = self.home.write(relative, text)
        self.planted.append(path)
        return path

    def link(self, relative, target):
        path = self.home.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        return path

    def turn(self, *paths, env=None):
        """One `ak worker` turn in HOME probing `paths`; what it saw.  Each planted file is
        still the host's after it."""
        seen = self.home.path / "seen.json"
        seen.unlink(missing_ok=True)
        self.fake.behave({"sh": shlex.join([sys.executable, "-I", "-c", PROBE, *map(str, paths)])})
        runs = self.fake.n
        done = self.home.ak("worker", "beta", str(self.task), "--workspace", str(self.home.path),
                            "--out", str(self.home.root / "out" / str(runs)), env=env)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.fake.n, runs + 1, done.err)
        self.assertEqual([path.read_text() for path in self.planted], [SECRET] * len(self.planted))
        return json.loads(seen.read_text())

    def assertNothing(self, seen, *paths):
        self.assertEqual(seen["paths"], {str(path): [] if path.is_dir() else "" for path in paths})

    def test_github_tokens_are_unset_and_credential_files_and_folders_hold_nothing(self):
        xdg, cache, gh = (self.home.path / name for name in ("xdg", "xdg-cache", "gh"))
        login, store = self.plant("login"), self.plant("store")
        self.plant(".git-credential-cache/socket")
        self.plant("xdg-cache/git/credential/socket")
        named = self.plant("named-store")
        with (self.home.path / ".gitconfig").open("a") as config:
            config.write('[credential]\n\thelper = store --file "~/named-store"\n')
        paths = [self.link(".config/gh/hosts.yml", login), self.link(".git-credentials", store),
                 login, store, self.plant("xdg/gh/hosts.yml"), self.plant("xdg/git/credentials"),
                 self.plant("gh/hosts.yml"), self.home.path / ".git-credential-cache",
                 cache / "git/credential", named]
        seen = self.turn(*paths, env={**dict.fromkeys(TOKENS, "fixture-token"),
                                      "XDG_CONFIG_HOME": str(xdg), "XDG_CACHE_HOME": str(cache),
                                      "GH_CONFIG_DIR": str(gh)})
        self.assertEqual(seen["env"], dict.fromkeys((*TOKENS, "SSH_AUTH_SOCK")))
        self.assertNothing(seen, *paths)

    def test_ssh_keys_keys_linked_into_ssh_and_the_agent_are_out_of_reach(self):
        vault = self.plant("vault/id_linked")
        keys = self.plant("keydir/id_dir").parent
        self.link(".ssh/id_linked", "../vault/id_linked")
        self.link(".ssh/keys", keys)
        paths = [self.plant(".ssh/id_acme"), vault, keys / "id_dir"]
        with socket.socket(socket.AF_UNIX) as agent:
            # by its folder's descriptor: a socket's path must fit in 104 bytes, HOME's may not
            folder = os.open(self.home.path, os.O_RDONLY)
            try:
                agent.bind(f"/proc/self/fd/{folder}/agent.sock")
            finally:
                os.close(folder)
            agent.listen()
            # an address relative to where ak was started, which is HOME
            for address in (str(self.home.path / "agent.sock"), "agent.sock"):
                with self.subTest(address=address):
                    seen = self.turn(*paths, env={"SSH_AUTH_SOCK": address})
                    self.assertEqual((seen["env"]["SSH_AUTH_SOCK"], seen["agent"]), (None, False))
                    self.assertNothing(seen, *paths)

    def test_a_turn_starts_where_the_host_s_ssh_paths_are_unusable(self):
        ssh, cache = self.home.path / ".ssh", self.home.path / ".git-credential-cache"
        # each case: what is made, and the agent address ak is given
        cases = {"a link to itself": (lambda: self.link(".ssh/self", "self"), None),
                 "two links to each other": (
                     lambda: (self.link(".ssh/a", "b"), self.link(".ssh/b", "a")), None),
                 "a looping .ssh": (lambda: self.link(".ssh", ".ssh"), None),
                 "a file named .ssh": (lambda: self.home.write(".ssh", "fixture"), None),
                 "an agent inside .ssh": (lambda: self.home.write(".ssh/agent", ""),
                                          ssh / "agent"),
                 "an agent inside Git's cache": (lambda: self.home.write(
                     ".git-credential-cache/agent", ""), cache / "agent")}
        for name, (make, agent) in cases.items():
            with self.subTest(case=name):
                make()
                self.turn(env={"SSH_AUTH_SOCK": agent and str(agent)})
                for path in (ssh, cache):
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                    elif path.exists():
                        shutil.rmtree(path)

    def test_a_file_or_folder_the_harness_reads_on_its_own_reads_empty(self):
        paths = [self.plant(".acme/AGENTS.md"), self.plant(".acme/rules/style.md").parent]
        self.assertNothing(self.turn(*paths, paths[1] / "style.md"), *paths,
                           paths[1] / "style.md")

    def test_git_s_credential_query_sees_no_token(self):
        # The git first on ak's PATH says what each call was given, then is the real one.
        self.home.fake("git", f"#!{sys.executable}\nimport json, os, sys\ntry:\n"
                              f"    with open({str(self.home.log('git'))!r}, 'a') as log:\n"
                              f"        log.write(json.dumps([sys.argv[1:], "
                              f"[os.environ.get(k) for k in {TOKENS!r}]]) + '\\n')\n"
                              f"except OSError:\n    pass\n"
                              f"os.execv({GIT!r}, [{GIT!r}, *sys.argv[1:]])\n")
        self.turn(env={**dict.fromkeys(TOKENS, "fixture-token"), "SSH_AUTH_SOCK": "agent"})
        calls = self.home.calls("git")
        self.assertTrue(any("credential" in " ".join(argv) for argv, _ in calls), calls)
        self.assertEqual([tokens for _, tokens in calls], [[None] * len(TOKENS)] * len(calls))

    def test_ak_asks_its_own_git_never_the_workspace_s(self):
        # PATH's relative entries, `bin` and the empty one, name the workspace's own Git; it
        # leaves a mark where only something outside the turn's box can write.
        asked = self.home.root / "asked"
        for relative in ("bin/git", "git"):
            self.home.write(relative, f"#!/bin/sh\n: >{shlex.quote(str(asked))} 2>/dev/null\n"
                                      f"exec {shlex.quote(GIT)} \"$@\"\n").chmod(0o755)
        # Git's own configuration, read wherever it lives, names a store to hide.
        store = self.plant("named-store")
        self.home.write(".ssh/git.inc", f"[credential]\n\thelper = store --file {store}\n")
        with (self.home.path / ".gitconfig").open("a") as config:
            config.write(f"[include]\n\tpath = {self.home.path / '.ssh/git.inc'}\n")
        seen = self.turn(store, env={"PATH": f"bin{os.pathsep}{os.pathsep}"
                                             + self.home.env["PATH"]})
        self.assertNothing(seen, store)
        self.assertFalse(asked.exists())


if __name__ == "__main__":
    unittest.main()
