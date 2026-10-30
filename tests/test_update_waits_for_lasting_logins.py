"""The tick starts a check only when the logins it lends will outlast it.

Offline, on the tick's own clock: `acme` is a fake adapter whose `auth` and `lend` use files under
a temporary HOME, git answers from a table, and nothing is really started.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, lend, orch, update

T = 1_000_000.0     # the first tick's clock
TICK = 180
TIP, OLD = "a" * 40, "c" * 40
MANIFEST = """version = 1
[worker]
logins = ["~/.acme/login"]
[update]
version = ["acme", "--version"]
upgrade = ["acme", "upgrade"]
latest = ["acme-latest"]
"""
# ends: when the login lapses, none where it lends none; renewed: what `auth seat` makes it
ADAPTER = """#!/bin/sh
root={root}
case "$1" in
  auth) echo "$*" >>"$root/auths"
        [ "$2" != seat ] || [ ! -e "$root/renewed" ] || mv "$root/renewed" "$root/ends"
        echo fine ;;
  lend) echo "$2" >>"$root/homes"
        [ ! -e "$root/lend-fails" ] || exit 3
        [ -e "$root/ends" ] || exit 1
        mkdir -p "$2/.acme" && echo copy >"$2/.acme/login" && cat "$root/ends" ;;
esac
"""
FILES = {"adapters/acme.toml": MANIFEST, "adapters/acme.sh": ADAPTER,
         "agentkit/tests/live.sh": "exit 0\n", "bin/acme": "#!/bin/sh\necho 1.0.0\n",
         "bin/acme-latest": '#!/bin/sh\necho asked >>"{root}/asks"\necho 2.0.0\n'}
CHECKING = f"checking agentkit at {TIP[:12]} with tests/live.sh before it goes live"
UPGRADING = "acme 1.0.0 is behind 2.0.0: upgrading it in the background"


def waits(what, ends):
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ends))
    return f"{what} waits: acme's login lapses at {when}, before it could end"


class WaitsForLastingLogins(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-lasting-logins-")
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name).resolve()
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name, text in FILES.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text.format(root=root))
            (root / name).chmod(0o755)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
            config.ADAPTER_DIR_ENV: str(root / "adapters")}))
        stack.enter_context(patch.object(config, "HOME", root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        stack.enter_context(patch.object(config, "REPO", root / "agentkit"))
        cfg = {"models": {"acme-model": {"harness": "acme", "provider": "acme"}},
               "providers": {"acme": {}}}
        for module, name, value in ((update, "agentkit_dir", root / "agentkit"), (config, "load", cfg),
                                    (update, "left_as_is", ""), (update, "_alive", False)):
            stack.enter_context(patch.object(module, name, return_value=value))
        # no commit named here is in HEAD: the tip, or a check's
        stack.enter_context(patch.object(update, "_git", side_effect=lambda *args, **_kw: (
            (1, "") if args[0] == "merge-base" else (0, "b" * 40 if args[-1] == "HEAD" else TIP))))
        stack.enter_context(patch.object(update.gitcall, "no_auto_gc"))
        self.checks = stack.enter_context(patch.object(orch, "start_in_slice"))
        self.upgrades = stack.enter_context(patch.object(update, "start"))

    def write(self, **files):
        for name, text in files.items():
            (self.root / name).write_text(f"{text}\n")

    def read(self, name):
        path = self.root / name
        return path.read_text().splitlines() if path.exists() else []

    def live_tick(self, now):
        said = []
        update.live_tick(said.append, now, fetched=True)
        return said

    def upgrade_tick(self, now):
        said = []
        update.keep_current(said.append, now=now)
        return said

    def test_a_live_check_waits_while_a_lent_login_lapses_within_its_margin(self):
        update._note_pass("live", T - 110, T - 10)          # so its margin is 200
        self.write(ends=int(T + 199))
        self.assertEqual(self.live_tick(T), [waits("tests/live.sh", T + 199)])
        self.assertEqual(self.live_tick(T + TICK), [])      # said once
        self.checks.assert_not_called()
        self.assertEqual(self.read("auths"), ["auth seat"] * 2)
        self.write(ends=int(T + 2 * TICK + 200))            # lapses no sooner than the margin
        self.assertEqual(self.live_tick(T + 2 * TICK), [CHECKING])
        self.assertEqual(self.checks.call_args.args[0][5], TIP)
        self.assertEqual(Path(self.read("homes")[0]).parents[1], config.TMP)    # lent aside
        self.assertEqual(list(config.TMP.glob("lend-*")), [])                   # and gone again

    def test_a_login_auth_seat_renews_is_lent_fresh(self):
        self.write(ends=int(T + 60), renewed=int(T + 8 * 3600))
        self.assertEqual(self.live_tick(T), [CHECKING])

    def test_a_harness_upgrade_waits_against_the_live_margin_plus_the_fresh_one(self):
        update._note_pass("live", T - 110, T - 10)
        update._note_pass("fresh", T - 210, T - 10)         # 200 + 400
        self.write(ends=int(T + 599))                       # past the live margin alone
        self.assertEqual(self.upgrade_tick(T), [waits("acme's upgrade", T + 599)])
        self.assertEqual(self.upgrade_tick(T + TICK), [])   # said once
        self.upgrades.assert_not_called()
        self.write(ends=int(T + 2 * TICK + 600))            # the first tick it lasts, not an hour on
        self.assertEqual(self.upgrade_tick(T + 2 * TICK), [UPGRADING])
        self.upgrades.assert_called_once_with("acme")
        self.assertEqual(self.read("asks"), ["asked"])      # the hour's one ask found the release
        self.assertEqual(self.upgrade_tick(T + 3 * TICK), [])

    def test_the_margin_follows_the_last_pass_doubled_and_capped(self):
        self.assertEqual((update.margin("live"), update.margin("fresh")),
                         (update.LIVE_CAP, update.E2E_CAP))
        update._note_pass("live", T, T + 210)
        update._note_pass("fresh", T, T + update.E2E_CAP - 1)
        self.assertEqual((update.margin("live"), update.margin("fresh")), (420, update.E2E_CAP))
        update._note_pass("live", T + 300, T + 400)
        self.assertEqual(update.margin("live"), 200)
        update._note_pass("live", T, T + 50)                # ended before the one on record
        self.assertEqual(update.margin("live"), 200)

    def test_the_tick_keeps_a_passing_live_check_and_no_other(self):
        for commit, began, ended, code in ((OLD, T, T + 100, 0), (TIP, T + 200, T + 500, 1)):
            check = config.STATE / update.LIVE / f"{commit}-{int(began)}"
            check.mkdir(parents=True)
            (check / "exit").write_text(f"{code}\n")
            os.utime(check / "exit", (ended, ended))
        self.live_tick(T + 600)
        self.assertEqual(update.margin("live"), 200)

    def test_a_gate_keeps_its_own_pass_and_no_skip_or_failure(self):
        clock = [T]
        takes = lambda result: lambda *_a, **_kw: clock.__setitem__(0, clock[0] + 100) or result
        with tempfile.NamedTemporaryFile(mode="w", dir=self.root) as log, \
                patch.object(update, "time", Mock(time=lambda: clock[0])):
            for key, ran, took in (("live", False, None), ("live", True, 100),
                                   ("fresh", (False, "failed"), None),
                                   ("fresh", (False, "skipped: no room"), None),
                                   ("fresh", (True, "passed"), 100)):
                with patch.object(update, "step", takes(ran)), \
                        patch.object(update, "fresh_gate", takes(ran)):
                    update.run_gate(key, log)
                self.assertEqual(update._last_pass(key)[1], took)

    def test_a_lend_that_fails_holds_nothing_back(self):
        self.write(ends=int(T + 60), **{"lend-fails": ""})
        self.assertEqual(self.live_tick(T), [CHECKING])
        self.assertEqual(self.upgrade_tick(T), [UPGRADING])

    def test_a_harness_lent_none_holds_nothing_back(self):
        self.assertEqual(self.live_tick(T), [CHECKING])
        self.assertEqual(self.upgrade_tick(T), [UPGRADING])

    def test_a_gates_own_lending_renews_nothing(self):
        self.write(ends=int(T + 60), renewed=int(T + 8 * 3600))
        with tempfile.TemporaryDirectory(dir=self.root) as home:
            self.assertEqual(lend.into(home)[1], (int(T + 60), "acme"))
        self.assertEqual(self.read("auths"), [])

    def test_a_manual_update_starts_at_once(self):
        self.write(ends=int(T + 60))
        with patch.object(update, "working_sessions", return_value=[]), \
                patch.object(update, "upgrade", return_value=0) as upgrade, \
                patch.object(update, "update_self", return_value=0):
            self.assertEqual(update.main([]), 0)
        upgrade.assert_called_once()
        self.assertEqual(self.read("auths"), [])


if __name__ == "__main__":
    unittest.main()
