"""While a turn runs on a machine, a renewal of its account's login here replaces its copy there, by
rename, sending only a change down the turn's own connection and trying a failed replacement again;
no process's command line holds it, a send landing after the turn ended leaves nothing, and the
following ends before the results come.

Black-box, as tests/test_key_a_turn_runs_on_a_machine.py: the executor's stand-in harness (FOLLOWS)
watches its lent file while it changes the login here, saying on `never` what never came; ssh logs
each verb and acts on the flags it is left.
"""

import base64
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "helper"
TOKEN = secrets.token_hex(16)    # its own: the process table it is sought in is the whole host's
HELD = Path(fakeadapter.LENT)
# Lends what the account's file here holds; an empty one lends nothing.
LEND = r"""#!/bin/sh
if [ "$1" = lend ]; then
  login="{dir}/${{AGENTKIT_ACCOUNT:-usual}}.login"
  echo lend >>"{dir}/lends"
  [ -s "$login" ] || exit 1
  mkdir -p "$2/{folder}" && cp "$login" "$2/{lent}" && echo "$(($(date +%s) + 86400))"
  exit
fi
"""
SSH = r"""#!/bin/bash
printf '%s\n' "$*" >>"{args}"
rest=${{@: -1}} rest=${{rest##*" mac.sh "}} verb=${{rest%% *}}
echo "$verb" >>"{verbs}"
renew() {{ cp "{dir}/$1" "{dir}/part"; mv "{dir}/part" "{dir}/second.login"; }}
case $verb in
prepare)    # the first turn's: renewed after the lend its parcel holds
  [ ! -e "{dir}/at-prepare" ] || {{ rm "{dir}/at-prepare"; renew one; }} ;;
collect|finish)
  find "{tree}" -path "{tree}/*/home/*" -type f 2>/dev/null >>"{seen}"
  # Renewed as results come home, with time for a follower still looking to send it.
  [ "$verb" != collect ] || {{ renew five; sleep 1; }} ;;
esac
exec "{real}" "$@"
"""
FOLLOWS = r"""#!/bin/bash
here={dir} mine="$HOME/{lent}" said=${{AK_HAND_IN%/*}}
holds() {{ cmp -s "$here/$1" "$mine"; }}
renew() {{ cp "$here/$1" "$here/part" && mv "$here/part" "$here/$2.login"; }}
lent_since() {{ [ "$(wc -l <"$here/lends")" -gt "$1" ]; }}
counted() {{ n=$(wc -l <"$here/lends"); "$@"; until_ lent_since "$n"; }}
until_() {{    # the process table read at each wait, by a pattern no command line of its own holds
  for _ in $(seq 2400); do
    "$@" && return
    ps -eww -o args | grep -F -f "$here/token" >>"$said/on-a-command-line"
    sleep 0.05
  done
  echo "$*" >>"$said/never"
}}
until_ holds one    # the renewal as it prepared
# Open on the old file, as a harness reading at that moment is: it stays whole, so it was a rename.
exec 3<"$mine"
renew two second
until_ holds two
cmp -s "$here/one" /dev/fd/3 || echo "the old file changed" >>"$said/never"
# The same bytes touched, then another account's login changing: each is lent, neither is sent, so
# the file stays the one it was, as it does when there is nothing to lend.
same=$(stat -c %i "$mine")
counted touch "$here/second.login"
counted renew three usual
: >"$here/empty"
counted renew empty second
sleep 1
[ "$(stat -c %i "$mine")" = "$same" ] || echo "an unchanged copy was sent" >>"$said/never"
renew three second
until_ holds three
"""


class ATurnLivesThroughItsLoginRenewal(unittest.TestCase):
    def test_the_renewal_reaches_the_turn_and_no_copy_stays(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ntests: true\n---\n# widgets\n",
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        GitHub(home).grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"],
                       providers={"anthropic": {"mode": "subscription", "accounts": ["second"]}},
                       settings={"suite_helper": "acme-linux", "turns_on_machines": True})
        here = home.root / "adapters"
        fakes = fakeadapter.install(home, codex="pass",
                                    claude={**fakeadapter.WORK, "sh": f"bash {here}/follows"})
        for name in ("second.login", "usual.login", "one", "two", "three", "four", "five"):
            (here / name).write_text(json.dumps({"token": f"{TOKEN}-{name}"}))
        (here / "token").write_text(f"{TOKEN}\n")
        (here / "at-prepare").touch()
        (here / "follows").write_text(FOLLOWS.format(dir=here, lent=HELD))
        script = fakes["claude"].script
        script.write_text(LEND.format(dir=here, lent=HELD, folder=HELD.parent)
                          + script.read_text().removeprefix("#!/bin/sh\n"))
        logins = [f"{here}/usual.login", f"{here}/$AGENTKIT_ACCOUNT.login"]
        with fakes["claude"].manifest.open("a") as manifest:
            manifest.write(f"logins = {json.dumps(logins)}\n")
        machine = akmachine.install(home)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        logs = {name: machine / f"{name}.log" for name in ("args", "verbs", "seen")}
        real = home.bin / "ssh.real"
        (home.bin / "ssh").rename(real)
        home.fake("ssh", SSH.format(real=real, dir=here, lent=HELD,
                                    tree=machine / "home/.agentkit-helper", **logs))
        done = home.ak("run", str(taskfile.write(home, rig.path)), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(home)
        self.assertTrue(json.loads((run / "run.json").read_text())["merged"])
        self.assertEqual([path.read_text() for path in run.rglob("never")], [])
        self.assertEqual([path.read_text() for path in run.rglob("on-a-command-line")], [""])
        self.assertNotIn(TOKEN, logs["args"].read_text())
        for path in run.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes(), path)
        # the late send included, nothing stayed for `collect` or `finish` to find, or after them
        self.assertNotIn(HELD.name, logs["seen"].read_text())
        self.assertEqual([*machine.rglob(f"{HELD.name}*")], [])


class TheVerbLeavesNothingBehind(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="relend-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.tree = self.home / ".agentkit-helper"
        (self.tree / "turn/home" / HELD.parent).mkdir(parents=True)
        (self.tree / "turn/lent").write_text(f"{HELD}\0.fake/gone.json\0")
        self.held = self.tree / "turn/home" / HELD
        self.held.write_text("old\n")
        self.other = self.held.with_name(f"{HELD.name}.part")    # a harness's own, named as a part
        self.other.write_text("old\n")
        self.beside = lambda: sorted(path.name for path in self.held.parent.iterdir())
        self.env = {"HOME": str(self.home), "PATH": os.environ["PATH"]}

    def verb(self, *argv, sent=b""):
        script = (TOOLS / "linux.sh").read_text() + (TOOLS / "mac.sh").read_text()
        return subprocess.run(["bash", "-c", script, "mac.sh", *argv], input=sent, env=self.env,
                              capture_output=True)

    def machine(self, call):
        script = (TOOLS / "linux.sh").read_text() + (TOOLS / "mac.sh").read_text()
        return subprocess.run(
            ["bash", "-c", script[:script.index('\ncase "$1" in')] + f"\n{call}"],
            env=self.env, capture_output=True, input=b"".join(
                base64.b64encode(f"{TOKEN}\n".encode()) + f" {path}\n".encode()
                for path in (HELD, ".fake/gone.json", f"{HELD}.part")))

    def renewals(self):
        return self.machine('renewals "$ROOT/turn"')

    def relend(self):    # one try, whose failure is what `renewals` tries again on
        return self.machine('locked "$ROOT/lent.lock" replace_lent "$ROOT/turn"')

    def test_it_writes_only_what_the_turn_s_list_names_and_it_still_holds_until_finish(self):
        self.assertEqual(self.renewals().returncode, 0)
        self.assertEqual(self.held.read_text(), f"{TOKEN}\n")
        self.assertEqual(self.held.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.other.read_text(), "old\n")
        self.assertEqual(self.beside(), [HELD.name, self.other.name])
        self.held.unlink()
        self.assertEqual(self.renewals().returncode, 0)
        self.assertEqual(self.beside(), [self.other.name])
        self.assertEqual(self.verb("finish", "turn").returncode, 0)
        self.renewals()
        self.assertEqual([path.name for path in self.tree.iterdir()], ["lent.lock"])

    def test_a_failed_rename_leaves_no_part_and_tells_its_caller(self):
        marks = self.home / "marks"
        marks.mkdir()
        (marks / "mv").write_text("#!/bin/sh\nexit 1\n")
        (marks / "mv").chmod(0o755)
        self.env["PATH"] = f"{marks}:{self.env['PATH']}"
        self.assertEqual(self.relend().returncode, 253)
        self.assertEqual(self.held.read_text(), "old\n")
        self.assertEqual(self.beside(), [HELD.name, self.other.name])

    def test_a_failed_rename_lands_on_the_next_try_on_the_same_connection(self):
        marks = self.home / "marks"
        marks.mkdir()
        fail = self.home / "fail"
        fail.touch()
        (marks / "mv").write_text(f'#!/bin/sh\nrm "{fail}" 2>/dev/null && exit 1\n'
                                  f'exec "{shutil.which("mv")}" "$@"\n')
        (marks / "mv").chmod(0o755)
        self.env["PATH"] = f"{marks}:{self.env['PATH']}"
        self.assertEqual(self.renewals().returncode, 0)
        self.assertFalse(fail.exists())
        self.assertEqual(self.held.read_text(), f"{TOKEN}\n")
        self.assertEqual(self.beside(), [HELD.name, self.other.name])

    def test_the_turn_s_end_removes_its_login_and_a_killed_send_s_part_and_nothing_else(self):
        (self.tree / "turn/harness").write_text("fake/1.0/program")
        (self.tree / "turn/work").touch()    # a volume with no room: it ends before any container
        self.held.with_name(f"{HELD.name}.ak-lent-abcdef").write_text(TOKEN)
        kept = self.held.with_name("session.ak-lent-checkpoint.json")
        kept.touch()
        self.verb("turn", "turn", "image", "256", "repo", "home:/acme", "work:/acme-work", "--")
        self.assertEqual(self.beside(), sorted([self.other.name, kept.name]))

    def test_a_send_waiting_on_the_turn_s_end_finds_the_login_gone(self):
        # The lock held as `turn`'s end holds it, until a `flock` on the send's PATH says it waits.
        marks = self.home / "marks"
        marks.mkdir()
        (marks / "flock").write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >"{marks}/args"\n'
                                     f'exec "{shutil.which("flock")}" "$@"\n')
        (marks / "flock").chmod(0o755)
        self.env["PATH"] = f"{marks}:{self.env['PATH']}"
        with open(self.tree / "lent.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            sending = threading.Thread(target=self.renewals)
            sending.start()
            while sending.is_alive() and not (marks / "args").exists():
                time.sleep(0.02)
            self.held.unlink()
        sending.join()
        self.assertEqual(self.beside(), [self.other.name])
        self.assertNotIn(base64.b64encode(TOKEN.encode()).decode(), (marks / "args").read_text())


if __name__ == "__main__":
    unittest.main()
