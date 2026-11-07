"""On a lived-in home, `ak orch list`, `ak orch why` and the ak screen's seat rows answer as on a
bare one.

The owner's `~/.agentkit/state` holds far more than seats: on 7 Nov 2026, 825 entries of 42
kinds, among them the suite's timings, the helper's memory, the warm menu's socket, Google Cloud's
records, the update's checks, the browser's tabs, the usage's pairs, a seat's done-check pictures,
the owner's notes and kinds nothing writes any more.  No seat's word, row or card reads them.  So
a home with two seats at their claude prompts is read bare, a first look's writes let through
before the answers kept, then again beside one entry of each kind, named and shaped as its writer
leaves it: each read's exit code, stderr and lines, and each seat file's word and reason, are the
bare home's, and every entry is left as it was.  Only what moves with the clock is left out: a
listed seat's age, which is tmux's since the seat's session began, the age in `since:`, and of
the screen all but its seat rows.  No tick runs: its passes write far more than a seat's word.
Black-box: the program `AK_BIN` names runs beside tests/fixtures/akseat.py's seats, and this test
fails against `/bin/false`.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

SEATS = ("acme", "beta")
STATE = ".agentkit/state"
LIST, SCREEN = ("orch", "list"), ()
READS = (LIST, *(("orch", "why", name) for name in SEATS), SCREEN)
WIDE = {"COLUMNS": "100"}

# Each entry as its writer names and shapes it.  Only one whose name carries a seat names one,
# acme; every other names another repository, run or login.
SHOP = "/home/acme/code/shop"                 # another repository's main checkout
REPO = hashlib.sha256(SHOP.encode()).hexdigest()    # gitcall.repository_id, leases.path
COMMIT = hashlib.sha1(b"shop").hexdigest()
MENU = "menu-%08x" % zlib.crc32(b"/home/acme/agentkit")  # warm.place: another checkout's menu
AT = 1793980800                               # 6 Nov 2026 16:00 UTC, when each was written
TIMES = json.dumps({"tests/test_cart.py": 2.4}, sort_keys=True)
TABS = json.dumps({"8F3A0C2E": {"first_seen": AT, "last_change": AT, "url": "https://example.com/",
                                "title": "Example"}}, indent=2) + "\n"
PAIRS = json.dumps({"anthropic": {"default": {"weekly_all": [{
    "at": AT, "tokens": 182000, "moved": 1.5, "resets_at": AT + 3 * 86400, "prior": 40.0,
    "model": "opus", "effort": "xhigh", "run_id": "20261106-1500-fix-cart", "role": "executor"}]}}})
PICTURE = json.dumps({"at": AT, "name": "cart.txt",
                      "data": base64.b64encode(b"cart: 2 items\n").decode()}) + "\n"
ATTRIBUTES = "*.md merge=ak-sentences\n"
ENTRIES = {
    # the suite's times and cost, and a write of one cut short (suite_times.keep, gate)
    f"test-times-{REPO[:12]}.json": TIMES,
    "suite-%s.json" % hashlib.sha256(f"{SHOP}\npython3 tests/run.py".encode()).hexdigest():
        json.dumps({"cpus": 2.5, "mem_mb": 1800, "quiet": [41.2]}),
    "tmpq7x2k_9d": TIMES[:12],
    # the helper's memory of a repository (helper.short)
    f"helper-memory-{REPO[:12]}": "4096\n",
    f".helper-memory-{REPO[:12]}.lock": "",
    f".helper-memory-{REPO[:12]}.tmp": "8192\n",
    # the warm menu's log and lock beside its socket (`bind`, warm.serve)
    f"{MENU}.log": "",
    f"{MENU}.lock": "",
    # Google Cloud's records (google_cloud)
    "google-cloud-late.json": json.dumps(["ak-3c5e7a9b1d2f listed idle, given back"], indent=2) + "\n",
    "google-cloud-ledger.json": json.dumps({"answered": AT, "spent": 1.25, "machines": {}},
                                           indent=2) + "\n",
    "google-cloud-offers.json": json.dumps({"at": AT, "offers": [[
        "c4d-standard-8", "europe-west4", 4, 30720, 0.142, ["europe-west4-a"],
        "projects/debian-cloud/global/images/family/debian-13", "Hyperdisk Balanced"]]},
        indent=2) + "\n",
    "google-cloud-need": "3500 tests\n",
    "google-cloud-need.taken": "3500 tests\n",
    "google-cloud-ssh-config": "Host *\n  Include ~/.ssh/config\n",
    # the update's checks, and what it last said (update)
    "harness-latest.json": json.dumps({"claude": {"asked": AT, "waits": ""}}),
    "harness-swaps.json": json.dumps([["claude", AT, AT + 40]]),
    "harness-gates/claude/handed": json.dumps({"reds": 1}),
    "live-check-passed": json.dumps([AT, 1500.0]),
    "live-check-passed.lock": "",
    "fresh-check-passed": json.dumps([AT, 2400.0]),
    "fresh-check-passed.lock": "",
    f"live-checks/{COMMIT}-{AT}/output": "PASS  tests/live.sh\n[exit 0]\n",
    f"live-checks/{COMMIT}-{AT}/exit": "0\n",
    "agentkit-said-watch": COMMIT + "\n",
    "agentkit-install-pending": "",
    "harness-update-said.json": json.dumps({"harness": "claude", "code": 0, "lines": []}),
    "live-check-held": "tests/live.sh waits: work's login lapses at 2026-11-06 17:00, "
                       "before it could end",
    "upgrade-check-held": "claude's upgrade waits: work's login lapses at 2026-11-06 17:00, "
                          "before it could end",
    # the browser's tabs, the usage's pairs, the owner's Discord name, a stall told
    # (browser, usage, notify, stuck)
    "browser-tabs.json": TABS,
    "browser-tabs.tmp": TABS,
    "capacity.json": PAIRS,
    "capacity.lock": "",
    "capacity.tmp-4242-1": PAIRS,
    "discord-user.json": json.dumps({"id": "412345678901234567", "name": "owner"}) + "\n",
    "stuck.json": json.dumps({
        "about": "the stall of the slot queue", "line": "ak stalled: 20261106-1500-fix-cart has "
        "been first in line for a slot for 41m", "typed": AT, "delivered": AT,
        "told": [f"slot:20261106-1500-fix-cart:{AT}"]}, indent=2) + "\n",
    # an antigravity launch's agent, made under its rulebook's name (adapters/antigravity.sh)
    "antigravity/rulebook-acme.Qx7mZ2/.agents/agents/agentkit/agent.md":
        "---\nname: agentkit\ndescription: the agentkit orchestrator seat\nsubagent: false\n"
        "tools:\n  - run_command\n---\n# rules\n",
    "antigravity/rulebook-acme.Qx7mZ2/.agents/hooks.json": json.dumps({"agentkit": {
        "PreInvocation": [{"type": "command", "command": "exit 0"}],
        "Stop": [{"type": "command", "command": "bash hooks/orchestrator-stop.sh"}]}},
        indent=2) + "\n",
    # what acme's deliveries and done checks kept (plan, done_check)
    "verified-acme.txt": "2\n1 The work is done\n",
    "unverified-acme.txt": "1\n",
    "unverified-acme.txt.new": "2\n",
    "pictures-acme.jsonl": PICTURE,
    "pictures-acme.jsonl.new": PICTURE * 2,
    # kinds nothing writes any more, and what the owner saved
    "compact-acme.json": json.dumps({"session": "acme", "harness": "claude",
                                     "last_compact_at": AT, "context_tokens": 151000}),
    "idle-compact/log": "2026-11-06T16:00:00+00:00 pid=4242 ignored state written for pid=4243 "
                        "(this seat is pid=4244)\n",
    "kept-logins.json": json.dumps([["anthropic", "work", "work"]], indent=2) + "\n",
    "launch.lock": "",
    f"leases/shop-{REPO[:16]}.json": json.dumps({"20261106-1500-fix-cart": {
        "files": ["cart.py"], "since": AT, "waits_on": "20261106-1400-fix-api"}},
        indent=1, sort_keys=True) + "\n",
    "leases/.lock": "",
    "openai-reset.json": json.dumps({"resets_at": AT + 86400}),
    "reported-by-monitor": "",
    "watch-before-move.log": "2026-10-30 09:00:00 tick ended in 12.5 s\n",
    "ideas.md": "# ideas\n\n- a cart that remembers\n",
    "todo.txt": "ship the cart\n",
    "scratch-cart.json": json.dumps({"items": 2}),
    # git's attributes, named by their text (gitcall)
    "merge-attributes/" + hashlib.sha256(ATTRIBUTES.encode()).hexdigest()[:16]: ATTRIBUTES,
    # read by the screen and a seat's card, holding nothing for them
    "notices": "",
    "login-refusals.json": "{}\n",
    ".login-refusals.lock": "",
}
SOCKET = f"{MENU}.sock"
# merged into watch.json as the owner's holds them: no news, and claude logged in
WATCH = {"seats_mb": 2310, "quiet": {},
         "auth_out": {"claude": {"ok": True, "why": "", "at": AT}}}


def steady(argv, out):
    """The lines of a read that do not move with the clock."""
    if argv == SCREEN:
        return [line for line in out.splitlines() if set(line.split()) & set(SEATS)]
    if argv == LIST:    # a live seat's age is tmux's, since its session began
        return [line.rsplit(None, 1)[0] if line.split()[:1] in ([name] for name in SEATS)
                else line for line in out.splitlines()]
    return [line.partition(" (")[0] if line.lstrip().startswith("since:") else line
            for line in out.splitlines()]


def answers(home):
    """Each read's exit code, stderr and steady lines, and each seat file's word and reason."""
    said = {}
    for argv in READS:
        done = home.ak(*argv, input="\n" if argv == SCREEN else None, env=WIDE)
        said[argv] = done.code, done.err, steady(argv, done.out)
    for name in SEATS:
        seat = json.loads((home.path / STATE / f"seat-{name}.json").read_text())
        said[name] = seat.get("word"), seat.get("reason")
    return said


def bind(state, name):
    """A socket bound by its bare name from inside `state`, as warm.serve binds its own: a
    sandbox's path is past a socket's 108 bytes."""
    here = os.open(".", os.O_RDONLY)
    try:
        os.chdir(state)
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(name)
    finally:
        os.fchdir(here)
        os.close(here)


def held(home):
    """Each entry added, as it is now: a file's bytes, else whether it is a socket."""
    state = home.path / STATE
    return {name: (state / name).read_bytes() if (state / name).is_file()
            else (state / name).is_socket() for name in [*ENTRIES, SOCKET]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LivedInHome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        made = int(time.time()) - 3600
        for at, name in enumerate(SEATS):
            Seat(home, name, record={"created": made + 60 * at})
        answers(home)           # a first look writes what it writes
        cls.bare = answers(home)
        for name, text in ENTRIES.items():
            home.write(f"{STATE}/{name}", text)
        bind(home.path / STATE, SOCKET)
        watch = home.path / STATE / "watch.json"
        home.write(f"{STATE}/watch.json", {
            **(json.loads(watch.read_text()) if watch.exists() else {}), **WATCH})
        cls.added = held(home)
        cls.lived = answers(home)

    def test_the_bare_home_answers(self):
        for argv in READS:
            code, err, _ = self.bare[argv]
            self.assertEqual(code, 0, f"ak {' '.join(argv)}: {err}")
        for argv in (LIST, SCREEN):
            shown = self.bare[argv][2]
            self.assertLessEqual(set(SEATS), {word for line in shown for word in line.split()},
                                 shown)

    def test_orch_list_answers_as_on_the_bare_home(self):
        self.assertEqual(self.lived[LIST], self.bare[LIST])

    def test_orch_why_answers_as_on_the_bare_home(self):
        for name in SEATS:
            argv = ("orch", "why", name)
            self.assertEqual(self.lived[argv], self.bare[argv], name)

    def test_the_screen_s_seat_rows_read_as_on_the_bare_home(self):
        self.assertEqual(self.lived[SCREEN], self.bare[SCREEN])

    def test_each_seat_file_keeps_the_bare_home_s_word_and_reason(self):
        for name in SEATS:
            self.assertEqual(self.lived[name], self.bare[name], name)

    def test_every_entry_added_is_left_as_it_was(self):
        self.assertEqual(held(self.home), self.added)
        watch = json.loads((self.home.path / STATE / "watch.json").read_text())
        self.assertEqual({key: watch.get(key) for key in WATCH}, WATCH)


if __name__ == "__main__":
    unittest.main()
