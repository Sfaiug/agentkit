"""The seat guard: a seat's tmux shim refuses ending or typing into another seat, and runs the
real tmux otherwise.

Offline: the shim is `tmux` first on PATH; a fake real tmux sits behind it, lists one server's
sessions, and resolves a `-t` target to its session the way tmux would -- through the read-only
command of the matching target type the guard uses (`list-windows -t` for a session target,
`list-panes -t` for a window, `display-message -t` for a pane). The fake mirrors tmux 3.5a's
quirk that a pane target does not treat `=name` as an exact session, so the test proves the guard
resolves each command with its own target type. No real tmux server is asked or touched.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "tools/tmux-shim"
# The fake real tmux: lists mine/other-seat/plain/404-page on the default server (other-seat on
# `-L other`), and resolves a -t target to its session per the resolver's target type. A run of it
# appends its argv to ran.log, so the test can tell a refusal from a pass-through.
REAL = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$RAN_LOG"
server=main; t=""; cmd=""
while [[ $# -gt 0 ]]; do
  case $1 in
    -L) [[ $2 == other ]] && server=other; shift 2 ;;
    -S) shift 2 ;;
    -t) t=$2; shift 2 ;;
    -*) shift ;;
    *) [[ -z $cmd ]] && cmd=$1; shift ;;
  esac
done
resolve() {                                   # $1=target, $2=flavor (session|window|pane)
  local x=$1 flavor=$2 exact=0
  case $x in :*|.*) echo mine; return ;; esac  # current-relative: the seat's own ($TMUX pane)
  [[ $flavor == pane && $x == =* ]] && return  # a pane target keeps the = literal: no exact session
  [[ $x == =* ]] && exact=1
  local s=${x#=}; s=${s%%:*}
  case $x in *:*) ;; *) s=${s%%.*} ;; esac     # with no colon, a .pane suffix is not the session
  if [[ $exact == 1 ]]; then
    case $s in mine) echo mine ;; plain) echo plain ;; other-seat) echo other-seat ;; 404-page) echo 404-page ;; esac
    return
  fi
  case $s in
    %*|@*|'~'|'{marked}'|/dev/*) echo other-seat ;;
    '$0') echo mine ;; '$1') echo other-seat ;; '$2') echo plain ;;
    mine|mi) echo mine ;;
    plain|pl) echo plain ;;
    other-seat|other|oth) echo other-seat ;;
    404|404-page) echo 404-page ;;
    *'*'*|*'['*|*'?'*) echo other-seat ;;
  esac
}
case $cmd in
  list-sessions)
    if [[ $server == other ]]; then printf '$0\tother-seat\n'
    else printf '$0\tmine\n$1\tother-seat\n$2\tplain\n$3\t404-page\n'; fi ;;
  list-windows)    resolve "$t" session ;;    # kill-session's resolver: a session target
  list-panes)      resolve "$t" window ;;     # kill-window's resolver: a window target
  display-message) resolve "$t" pane ;;       # every pane-targeted command's resolver
esac
exit 0
"""
# A guarded command whose -t falls on another seat, by the command's own target type.
REFUSED = (["kill-session", "-t", "other-seat"],
           ["kill-ses", "-t", "other"],                 # tmux's unique prefixes
           ["kill-session", "-t", "=other-seat"],       # exact: a session target, not a pane
           ["kill-window", "-t", "=other-seat"],        # exact: a window target
           ["kill-session", "-t", "404"],               # a digit prefix is a session name
           ["kill-server"],
           ["-L", "agentkit", "kill-server"],
           ["kill-session", "-a", "-t", "mine"],        # every session but this seat's
           ["kill-session", "-t", "$1"],                # a session id
           ["kill-session", "-t", "oth*"],              # a pattern
           ["kill-session", "-tother-seat"],            # the value in the same word
           ["-uL", "agentkit", "kill-session", "-t", "other-seat"],   # grouped before -L
           ["--", "kill-session", "-t", "other-seat"],  # end-of-options marker
           ["kill-window", "-t", "other-seat:0"],       # a window of another seat
           ["kill-pane", "-t", "other-seat:0.0"],
           ["kill-pane", "-t", "other-seat.0"],         # a pane with no colon -> session prefix
           ["killp", "-t", "other-seat:0.1"],           # an alias
           ["send-keys", "-t", "other-seat", "hello", "Enter"],
           ["send-keys", "-t", "other-seat.0", "x"],
           ["send-keys", "-N", "2", "-t", "other-seat", "Enter"],     # a valued option before -t
           ["send", "-t", "other-seat", "x"],           # an alias
           ["paste-buffer", "-t", "other-seat"],        # tmux's other way to type into a pane
           ["pasteb", "-t", "other-seat"],              # an alias
           ["paste-buffer", "-b", "buf", "-t", "other-seat"],         # -b takes a value
           ["send-prefix", "-t", "other-seat"],         # sends the prefix key to the pane
           ["pipe-pane", "-I", "-t", "other-seat"],     # -I pipes into the pane
           ["ls", ";", "kill-session", "-t", "other-seat"],         # a kill chained after `;`
           ["ls;", "kill-session", "-t", "other-seat"],             # ... with `;` attached
           ["send-keys", "-t", "mine", "x", ";", "send-keys", "-t", "other-seat", "y"],
           ["-L", "other", "kill-session", "-t", "other-seat"])      # on a named server
# Own targets, non-seat sessions, and -- by design -- what the guard leaves to the real tmux: a
# `-t` left off, a pane target's `=name` (which tmux finds no pane for), and every command that
# moves, replaces or respawns a pane or window. The bypass-proof form is a per-seat socket (en2f).
ALLOWED = (["kill-session", "-t", "mine"],
           ["kill-session", "-t", "plain"],             # not a seat ak records
           ["kill-session", "-t", "=other"],            # exact: no session named just "other"
           ["ls"],
           ["kill-window", "-t", ":0"],                 # a window of this seat's own session
           ["kill-pane", "-t", ":0.0"],
           ["kill-session", "-C", "-t", "other-seat"],  # -C clears alerts; the session lives
           ["send-keys", "-t", "mine", "x", "Enter"],
           ["send-keys", "-t", "mine", "make;kill-server", "Enter"],  # `;` mid-word is literal text
           ["send-keys", "x", "Enter"],                 # no -t: the current pane, this seat's own
           ["kill-pane", "-t", "=other-seat"],          # a pane target: tmux finds no such pane
           ["send-keys", "-t", "=other-seat", "x"],
           ["-L", "other", "kill-session"],             # no -t: out of reach
           ["-L", "other", "send-keys", "x", "Enter"],
           ["pipe-pane", "-t", "other-seat"],           # no -I: reads the pane's output, types nothing
           ["pipe-pane", "-O", "-t", "other-seat"],
           # out of reach: the commands that move, replace or respawn a pane or window
           ["swap-pane", "-s", "other-seat:0.0", "-t", "mine:0.0"],
           ["move-pane", "-s", "other-seat", "-t", "mine"],
           ["join-pane", "-s", "other-seat"],
           ["break-pane", "-s", "other-seat"],
           ["respawn-pane", "-k", "-t", "other-seat"],
           ["respawn-window", "-k", "-t", "other-seat"],
           ["new-window", "-k", "-t", "other-seat:0"],
           ["unlink-window", "-t", "other-seat:0"],
           ["move-window", "-s", "other-seat:0", "-t", "mine:9"],
           ["swap-window", "-s", "other-seat:0", "-t", "mine:0"],
           ["link-window", "-s", "mine:0", "-t", "other-seat:0"])


class TmuxShim(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".agentkit/state").mkdir(parents=True)
        for s in ("mine", "other-seat", "404-page"):
            (self.home / f".agentkit/state/session-{s}.json").write_text("{}\n")
        self.shimdir = self.home / "shim"
        self.realdir = self.home / "real"
        self.shimdir.mkdir()
        self.realdir.mkdir()
        (self.shimdir / "tmux").symlink_to(SHIM)        # the shim is `tmux`, first on PATH
        real = self.realdir / "tmux"
        real.write_text(REAL)
        real.chmod(0o755)
        self.ran = self.home / "ran.log"
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("AK_RUN_ROLE", "AGENTKIT_SESSION")}
        self.env.update(HOME=str(self.home), AGENTKIT_SESSION="mine", RAN_LOG=str(self.ran),
                        PATH=f"{self.shimdir}{os.pathsep}{self.realdir}{os.pathsep}{os.environ.get('PATH', '')}")

    def run_tmux(self, args, **env):
        self.ran.write_text("")
        result = subprocess.run([str(self.shimdir / "tmux"), *args], capture_output=True,
                                text=True, timeout=30, env={**self.env, **env})
        ran = self.ran.read_text() if self.ran.exists() else ""
        return result, ran

    def test_ending_or_typing_into_another_seat_is_refused(self):
        for args in REFUSED:
            with self.subTest(args=args):
                result, ran = self.run_tmux(args)
                self.assertEqual(result.returncode, 1, (args, result.stderr))
                self.assertIn("other-seat" if "404" not in "".join(args) else "404-page",
                              result.stderr)
                self.assertIn("another seat", result.stderr)
                self.assertNotIn("kill-session\n", ran + "\n")   # the real tmux never ran the kill

    def test_typing_into_another_seat_is_refused(self):
        for args in (["send-keys", "-t", "other-seat", "x", "Enter"],
                     ["paste-buffer", "-t", "other-seat"],
                     ["pasteb", "-dt", "other-seat"],
                     ["send-prefix", "-t", "other-seat"],
                     ["pipe-pane", "-I", "-t", "other-seat"]):
            with self.subTest(args=args):
                result, ran = self.run_tmux(args)
                self.assertEqual(result.returncode, 1, (args, result.stderr))
                self.assertIn("type into other-seat", result.stderr)
                self.assertIn("typed into another seat", result.stderr)

    def test_own_out_of_reach_and_non_seat_sessions_run_the_real_tmux(self):
        for args in ALLOWED:
            with self.subTest(args=args):
                result, ran = self.run_tmux(args)
                self.assertEqual(result.returncode, 0, (args, result.stderr))
                self.assertTrue(ran.strip(), (args, "reached no real tmux"))   # it passed through

    def test_a_worker_and_a_non_seat_shell_run_the_real_tmux(self):
        kill = REFUSED[0]
        for env in ({"AK_RUN_ROLE": "worker"}, {"AGENTKIT_SESSION": ""}):
            with self.subTest(env=env):
                result, ran = self.run_tmux(kill, **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("kill-session", ran)

    def test_a_renamed_seat_runs_its_own_kill(self):
        (self.home / ".agentkit/state/session-mine.json").write_text(
            json.dumps({"renamed": "renamed-seat"}))
        (self.home / ".agentkit/state/session-renamed-seat.json").write_text("{}\n")
        (self.realdir / "tmux").write_text(
            REAL.replace("\\tmine\\n", "\\trenamed-seat\\n").replace(
                "mine|mi) echo mine ;;", "mine|mi) echo mine ;;\n    renamed-seat) echo renamed-seat ;;"))
        (self.realdir / "tmux").chmod(0o755)
        result, ran = self.run_tmux(["kill-session", "-t", "renamed-seat"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("kill-session", ran)


if __name__ == "__main__":
    unittest.main()
