"""Finding 14: execute extracted acceptance paths, entirely offline in temporary state.

Never invoke either live gate. Account/package/network commands are fakes; model work uses
the smoke suite's fake adapters. Even the tmux fake rejects every socket but agentkit-test.
"""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, terminal, update

SMOKE = (REPO / "tests/smoke.sh").read_text()
FRESH = (REPO / "tests/e2e-fresh.sh").read_text()


def between(text, start, end):
    return text[text.index(start):text.index(end, text.index(start))]


class AcceptanceGates(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".acceptance-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.sockets = self.root / "sockets"
        self.sockets.mkdir(mode=0o700)
        self.adapters = self.root / "adapters"
        self.adapters.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "WORK": str(self.root),
                    "REPO": str(REPO), "PATH": f"{self.bin}:{REPO / 'bin'}:{os.environ['PATH']}",
                    "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1",
                    "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
                    "AK_RUN_DEPTH": "0", "AK_PARENT_RUN": "",
                    "AGENTKIT_DISCORD_WEBHOOK": "off", "TMUX": "",
                    "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(self.sockets),
                    "AGENTKIT_ADAPTER_DIR": str(self.adapters), "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_CONFIG_NOSYSTEM": "1", "ACCEPTANCE_FIXTURE": str(self.root),
                    "AK_SLOT_POLL": ".05",
                    "AK_HOST_READINGS": json.dumps({"free_mb": 4096, "mem_total_mb": 16384,
                                                    "load": 1, "cpus": 8,
                                                    "unit_memory_current_mb": 100,
                                                    "unit_memory_high_mb": 1000})}
        # Reject accidental live entry points, including commands that a changed extraction
        # might introduce. No credentials, packages, accounts, services or network are touched.
        for name in ("getent", "sudo", "runuser", "useradd", "userdel", "chown", "install", "crontab",
                     "pkill", "systemctl", "service", "apt", "apt-get", "npm", "curl", "wget",
                     "ssh", "gh", "claude", "codex", "muse"):
            self.script(name, 'echo "forbidden external command: $0 $*" >&2; exit 97\n')
        self.script("tmux", '''[ "$1 $2" = '-L agentkit-test' ] || exit 97
case "$TMUX_TMPDIR" in "$ACCEPTANCE_FIXTURE"/*) ;; *) exit 97 ;; esac
exit 1
''')
        # Local repositories only, including all origins created by the extracted check 19.
        self.git_binary = shutil.which("git")
        self.script("git", f'''case "$PWD" in "$ACCEPTANCE_FIXTURE"|"$ACCEPTANCE_FIXTURE"/*) ;; *) exit 97 ;; esac
if [ "${{1:-}}" = -C ]; then
  case "$2" in "$ACCEPTANCE_FIXTURE"|"$ACCEPTANCE_FIXTURE"/*) ;; *) exit 97 ;; esac
fi
case "$*" in *"remote add "*) ;; *https://*|*git@*|*ssh://*) exit 97 ;; esac
exec {shlex.quote(self.git_binary)} "$@"
''')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, self.env))
        self.stack.enter_context(patch.object(config, "HOME", self.home / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.home / "code"))
        config.ensure_dirs()
        self.common = '. "$REPO/tests/acceptance.sh"\n'
        self.newrepo = between(SMOKE, "newrepo()", 'echo "workdir:')
        self.fakeadapter = between(SMOKE, "fakeadapter()", 'cat >"$WORK/retry-task.md"')
        self.shell(self.fakeadapter + '''
for harness in claude codex muse; do fakeadapter "$AGENTKIT_ADAPTER_DIR" "$harness" pass; done
''', check=True)

    def script(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)
        return path

    def shell(self, body, *, check=False, env=None):
        result = subprocess.run(["/bin/bash", "-c", "set -uo pipefail\n" + self.common + body],
                                cwd=self.root, env={**self.env, **(env or {})},
                                text=True, capture_output=True, timeout=90)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_throwaway_home_shell_and_driver_need_no_privilege(self):
        for banned in ("asroot", "runas", "sudo", "useradd", "SUDO_USER"):
            self.assertNotIn(banned, FRESH)
        as_user = between(FRESH, "\nas()", "# A subscription login")
        drive = between(FRESH, "drive()", "# All supported harnesses")
        for block in (as_user, drive):
            self.assertIn('HOME=$UH', block)
            self.assertIn('AGENTKIT_TMUX_SOCKET', block)
            self.assertIn('TMUX_TMPDIR', block)
        result = self.shell(f'''{as_user}{drive}
UH="$WORK/new-home" INVOKER=donor AS_TERM=dumb
EPATH="$(dirname "$(command -v python3)"):/usr/bin:/bin"
E2E_TMUX_SOCKET=agentkit-test E2E_TMUX_DIR="$WORK/tmux" SEAT=""
mkdir -p -- "$UH" "$WORK/pty" "$E2E_TMUX_DIR"
as 'echo "home=$HOME user=$USER"'
# The driver only needs something executable past `--`; the real pty driver is
# exercised by the prompt tests below.
cat >"$WORK/ptydrive.py" <<'PY'
import os, sys
rest = sys.argv[sys.argv.index("--") + 1:]
os.execvp(rest[0], rest)
PY
: >"$WORK/probe.exp"
drive probe xterm-256color printenv HOME USER
''', check=True)
        self.assertIn('home=' + str(self.root / 'new-home'), result.stdout)
        self.assertIn('user=donor', result.stdout)
        driven = (self.root / 'probe.log').read_text()
        self.assertIn(str(self.root / 'new-home'), driven)
        self.assertIn('donor', driven)
        self.assertNotIn('command not found', result.stderr)

    def test_pipeline_failures_accumulate_in_parent_and_have_diagnostics(self):
        assertions = between(FRESH, 'bad="" ASSERTION=0', "# --- the throwaway HOME's shell")
        lines = '\n'.join(line for line in FRESH.splitlines() if line.startswith('  must "ak orch list'))
        result = self.shell(assertions + '\nLIST="wrong output"\n' + lines + '''
must "pipeline's producer failed" bash -o pipefail -c 'false | cat'
verdict fixture evidence
finish
''')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('0 passed, 1 failed, 0 skipped', result.stdout)
        self.assertIn('does not show the seat; ak orch list does not show its models;', result.stdout)
        self.assertIn("exit=1 log=", result.stdout)
        self.assertIn("command=grep", result.stdout)

    def test_menu_and_prompt_patterns_for_all_harnesses_and_pty_progress(self):
        prompt = re.search(r"^PROMPT='(.*)'$", FRESH, re.M).group(1)
        menu_pattern = re.search(r"^MENU='(.*)'$", FRESH, re.M).group(1)
        for footer in (menu.KEYS, menu.OVERLAY_KEYS):
            self.assertRegex(footer, menu_pattern)
        muse_footer = next(line.strip() for line in (REPO / 'tests/fixtures/muse-stall-pane.txt')
                           .read_text().splitlines() if line.strip().endswith(' · YOLO'))
        for harness, pane in (("claude", "bypass permissions on"),
                              ("codex", '› Ask Codex to do anything'), ("muse", muse_footer)):
            with self.subTest(harness=harness):
                self.assertRegex(pane, prompt)
                driver = between(FRESH, 'cat >"$WORK/ptydrive.py"', 'chmod 755 "$WORK/ptydrive.py"')
                self.shell(driver, check=True)
                (self.root / "dialog.exp").write_text(f'expect 2 {menu_pattern}\nsend n\\n\nexpect 2 {prompt}\n')
                child = self.root / "dialog.py"
                child.write_text(f'import sys\nprint({menu.KEYS!r}, flush=True)\ninput()\n'
                                 + ("print('Hooks need review\\n3. Continue without trusting', flush=True)\n"
                                    "assert input() == '3'\n" if harness == "codex" else "")
                                 + f'print({pane!r}, flush=True)\ninput()\n')
                self.shell('python3 "$WORK/ptydrive.py" "$WORK/transcript" "$WORK/dialog.exp" -- python3 "$WORK/dialog.py"', check=True)
        # Seeing the menu before a send cannot satisfy a later expect after the child exits.
        (self.root / "dialog.exp").write_text(f'expect 1 {menu_pattern}\nsend q\\n\nexpect 1 {menu_pattern}\n')
        (self.root / "dialog.py").write_text(f'print({menu.KEYS!r}, flush=True)\ninput()\n')
        self.assertNotEqual(self.shell('python3 "$WORK/ptydrive.py" "$WORK/transcript" "$WORK/dialog.exp" -- python3 "$WORK/dialog.py"').returncode, 0)
        self.assertNotIn("n new session", FRESH)

    def test_fresh_prompt_rejects_banners_cursors_and_authentication_dialogs(self):
        prompt = re.search(r"^PROMPT='(.*)'$", FRESH, re.M).group(1)
        nodialog = re.search(r"^NODIALOG='(.*)'$", FRESH, re.M).group(1)
        driver = between(FRESH, 'cat >"$WORK/ptydrive.py"', 'chmod 755 "$WORK/ptydrive.py"')
        self.shell(driver, check=True)
        auth = (REPO / 'tests/fixtures/codex-auth-pane.txt').read_text()
        banner = auth.split('  Tip:', 1)[0]
        for pane in (banner, '› 1. Review hooks', '⟩', 'YOLO',
                     banner + '\nSign in with ChatGPT\n› 1. Sign in', auth):
            with self.subTest(pane=pane):
                (self.root / 'dialog.exp').write_text(f'expect 0.2 {prompt}\nrefute {nodialog}\n')
                (self.root / 'dialog.py').write_text(f'print({pane!r}, flush=True)\ninput()\n')
                result = self.shell('python3 "$WORK/ptydrive.py" "$WORK/transcript" "$WORK/dialog.exp" -- python3 "$WORK/dialog.py"')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertRegex(result.stderr, 'MISSING|PRESENT but must not be')

    def test_fresh_hook_dialog_with_cursor_moves_is_declined_before_prompt(self):
        prompt = re.search(r"^PROMPT='(.*)'$", FRESH, re.M).group(1)
        driver = between(FRESH, 'cat >"$WORK/ptydrive.py"', 'chmod 755 "$WORK/ptydrive.py"')
        self.shell(driver, check=True)
        hooks = (REPO / 'tests/fixtures/codex-hooks-review-pane.txt').read_text()
        for spaces in (' ', '\x1b[1C'):
            with self.subTest(spaces=spaces):
                composer = '› Ask Codex to do anything'
                pane = (composer + '\n' + hooks).replace(' ', spaces)
                repaint = 'OpenAI Codex\x1b[10;2H' + composer.replace(' ', spaces)
                (self.root / 'dialog.exp').write_text(f'expect 2 {prompt}\n')
                (self.root / 'dialog.py').write_text(
                    f'print({pane!r}, flush=True)\nassert input() == "3"\n'
                    f'print({repaint!r}, flush=True)\ninput()\n')
                result = self.shell('python3 "$WORK/ptydrive.py" "$WORK/transcript" "$WORK/dialog.exp" -- python3 "$WORK/dialog.py"', check=True)
                self.assertNotIn('MISSING', result.stderr)

    def test_skipped_harness_browser_and_failed_run_prerequisite(self):
        skipped = between(SMOKE, "skip_spent()", "printf 'Create a file")
        loop = between(SMOKE, 'ABSENT=0\nfor pair in "opus claude"', '# --- 4:')
        browser = between(SMOKE, '# 31d/31e: real calls', '# --- 32:')
        prerequisite = between(SMOKE, '# --- 4d:', '\nfi\n\n# --- 5:').rsplit('\nfi', 1)[0] + '\nfi\n'
        result = self.shell('spent_until() { echo "provider tomorrow"; }\n' + skipped + loop
                            + 'skip_spent 4/4b/4c/4d opus astra\n'
                            + 'python3() { return 1; }  # fake unavailable browser probe\n' + browser
                            + '\nRC=1 RUNDIR=""\n' + prerequisite + '\nfinish',
                            env={"AGENTKIT_ACCEPTANCE_REQUIRED": "1"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        # 31d/31e: no shared browser is a host's absence, counted as passed; the rest are not.
        self.assertIn('2 passed, 0 failed, 11 skipped', result.stdout)
        self.assertIn('4d no dead orchestrator seat: prerequisite', result.stdout)
        self.assertIn('acceptance: INCOMPLETE', result.stdout)
        self.assertNotIn('PASS ', result.stdout)

    def test_codex_partial_hook_modal_is_not_a_ready_banner(self):
        poll = between(SMOKE, 'PANE=""\nfor _ in', '\ncp "$HOME/')
        result = self.shell('''tm() {
case "$1" in
  capture-pane)
    if [ -f "$WORK/continued" ]; then echo 'OpenAI Codex';
    elif [ -f "$WORK/partial" ]; then
      cat "$REPO/tests/fixtures/codex-hooks-review-pane.txt";
    else touch "$WORK/partial"; printf 'OpenAI Codex\\nHooks need review\\n'; fi ;;
  send-keys)
    [ "$*" = 'send-keys -t smoke-astra 3 Enter' ] || return 97
    touch "$WORK/continued" ;;
  *) return 97 ;;
esac
}
sleep() { :; }
''' + poll + '\ntest -f "$WORK/continued"\n', check=True)
        self.assertNotIn('forbidden', result.stderr)

    def test_usage_and_echo_diagnostics_show_actual_exit_and_error_tail(self):
        for start, end, code, log in (('# --- 1: usage', '# --- 2:', 23, 'usage.err'),
                                       ('# --- 2:', '# --- 3:', 24, 'echo.log')):
            with self.subTest(check=start):
                result = self.shell(self.newrepo + f'''ak() {{
echo Traceback >&2
for n in $(seq 1 25); do echo '  traceback frame' >&2; done
echo 'PermissionError: actual fixture failure' >&2
return {code}
}}
''' + between(SMOKE, start, end) + '\nfinish')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(f'exit={code} log={self.root / log}', result.stdout)
                self.assertIn('PermissionError: actual fixture failure', result.stdout)
                self.assertIn('command=', result.stdout)
                self.assertIn('0 passed, 1 failed, 0 skipped', result.stdout)

    def test_nonzero_usage_and_worker_exits_cannot_pass_with_good_output(self):
        result = self.shell(self.newrepo + '''ak() {
if [ "$1" = usage ]; then
  echo '{"pick_order":["astra"],"providers":{"anthropic":{"meters":[{}]},"openai":{"meters":[{}]}}}'
else
  mkdir -p "$WORK/o-echo"
  echo OK >"$WORK/o-echo/final.md"; echo fixture >"$WORK/o-echo/session_id"
fi
echo 'fixture error after writing outputs' >&2
return 42
}
''' + between(SMOKE, '# --- 1: usage', '# --- 3:') + '\nfinish')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('0 passed, 2 failed, 0 skipped', result.stdout)
        self.assertEqual(result.stdout.count('exit=42 log='), 2)

    def test_update_skips_unavailable_account_gate_and_still_upgrades(self):
        plan = [{"name": n, "version": [n, "--version"], "upgrade": [n, "install", "latest"],
                 "revert": [n, "install", update.VERSION_KEY], "env": {}, "cannot": "",
                 "snapshot_dir": ""} for n in ("claude", "codex")]
        calls = []
        (Path.home() / "agentkit" / ".git").mkdir(parents=True)
        with patch.object(update, "fresh_unavailable",
                          return_value="fixture: no account here"), \
                patch.object(update, "harnesses", return_value=plan), \
                patch.object(update, "version", return_value="1.0.0"), \
                patch.object(update, "step",
                             side_effect=lambda cmd, *a, **k: calls.append(cmd) or True), \
                patch.object(update, "working_sessions", return_value=[]), \
                patch.object(update, "update_agentkit", return_value=0) as selfmove:
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                code = update.main([])
                self.assertEqual(update.fresh_gate(None, lambda _: None),
                                 (False, "skipped: fixture: no account here"))
            self.assertEqual(code, 0)
            self.assertIn('skipped: fixture: no account here', output.getvalue())
            self.assertNotIn('nothing was upgraded or verified', output.getvalue())
            self.assertTrue(any(cmd[0] != "bash" for cmd in calls), "no upgrade ran")
            self.assertTrue(any(cmd[:2] == ["bash", str(update.config.REPO / "tests/smoke.sh")]
                                for cmd in calls), "the smoke gate did not run")
            selfmove.assert_called_once_with()
        with patch.object(update.sys, "platform", "darwin"):
            self.assertIn('Linux only', update.fresh_unavailable())
        with patch.object(update.sys, "platform", "linux"):
            self.assertEqual(update.fresh_unavailable(), "")

    def test_update_reverts_when_smoke_skips_required_live_coverage(self):
        versions = {h["name"]: "1.0.0" for h in update.harnesses()}
        self.script("muse", '''dir=${BASH_SOURCE[0]%/*}
exec "$dir/muse-bin-$(cat "$dir/.muse-version")" "$@"
''')
        self.script("muse-bin-1.0.0-R1", "echo 1.0.0-R1\n")
        (self.bin / ".muse-version").write_text("1.0.0-R1\n")
        (self.bin / ".muse-release-info.json").write_text('{"version":"1.0.0-R1"}\n')
        real_step = update.step
        real_version = update.version
        def step(cmd, fh, env=None, timeout=None):
            if cmd[0] == "bash":
                self.assertEqual(env["AGENTKIT_ACCEPTANCE_REQUIRED"], "1")
                return real_step(["/bin/bash", "-c", self.common + 'skip "3a codex: spent"; finish'], fh, env)
            if cmd[0] == "muse":
                self.script("muse-bin-2.0.0-R2", "echo 2.0.0-R2\n")
                (self.bin / "muse-bin-1.0.0-R1").unlink()
                (self.bin / ".muse-version").write_text("2.0.0-R2\n")
                (self.bin / ".muse-release-info.json").write_text('{"version":"2.0.0-R2"}\n')
                return True
            name = "codex" if cmd[0] == "npm" else cmd[0]
            versions[name] = "1.0.0" if cmd[-1].endswith("1.0.0") else "2.0.0"
            return True
        with patch.object(update, "fresh_unavailable", return_value=""), \
                patch.object(update, "version", side_effect=lambda h:
                             real_version(h) if h["name"] == "muse" else versions[h["name"]]), \
                patch.object(update, "step", side_effect=step):
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                code = update.main([])
        self.assertEqual(code, 1, output.getvalue())
        self.assertIn('INCOMPLETE', output.getvalue())
        self.assertIn('exit=2 log=', output.getvalue())
        self.assertIn('claude: reverted', output.getvalue())
        self.assertIn('muse: reverted, back on 1.0.0-R1', output.getvalue())
        self.assertTrue((self.bin / 'muse-bin-1.0.0-R1').is_file())
        self.assertFalse((self.bin / 'muse-bin-2.0.0-R2').exists())
        self.assertNotIn('smoke passed', output.getvalue())

    def test_updated_smoke_fake_upgrade_and_merge_fixtures(self):
        # Exercise the actual fake adapters and bare origin used by smoke check 19, with
        # the real loop. Every model invocation remains a generated offline adapter.
        for start, end in (('# --- 18b:', '# --- 19:'), ('# --- 19:', '# --- 20:')):
            with self.subTest(check=start):
                result = self.shell(self.newrepo + self.fakeadapter + '\nPYBIN="$WORK/bin"\n'
                                    + between(SMOKE, start, end) + '\nfinish')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('1 passed, 0 failed, 0 skipped', result.stdout)

    def test_smoke_recovery_and_retention_fixtures(self):
        task = between(SMOKE, 'cat >"$WORK/retry-task.md"', '# The first sleeps')
        block = between(SMOKE, '# --- 13:', '# --- 14:')
        result = self.shell(self.newrepo + self.fakeadapter + task + block + '\nfinish')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('3 passed, 0 failed, 0 skipped', result.stdout)

    def test_updated_watch_fixture(self):
        block = between(SMOKE, '# --- 23:', '# --- 24:')
        # The existing fixture supplies gh results. The only writes are its throwaway HOME.
        result = self.shell(self.newrepo + block + '\nfinish')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('2 passed, 0 failed, 0 skipped', result.stdout)

    def test_renderer_checks_new_menu_and_has_no_pager(self):
        block = between(SMOKE, '# --- 35:', '# --- result')
        self.assertIn('35a menu renderer', block)
        self.assertNotIn('35b', block)
        self.assertNotIn('runshost', block)
        self.assertNotIn('menu.runs_listing()', block)
        self.assertNotIn('menu.runs(', block)
        self.assertNotIn('menu.watch_run(', block)
        self.assertNotIn('menu.recover_run(', block)
        self.assertNotIn('menu.Feed', block)
        self.assertNotIn('menu.page', block)
        renderer = block.replace('cp "$MHOME/.agentkit/state/usage.json" "$RUNSH/.agentkit/state/usage.json"', ':')
        result = self.shell(renderer + '\nfinish')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS  35a', result.stdout)

    def test_menu_answers_c_i_and_refuses_r_without_a_pager(self):
        self.assertFalse(hasattr(menu, "page"))
        self.assertFalse(hasattr(menu, "Feed"))
        answers = iter(["c", "i", "r", "q", "q"])     # `c` and `i` read no line of their own
        with patch.object(orch, "listing", return_value=[]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "draw", return_value=(0, 1)), \
                patch.object(menu, "read", side_effect=lambda *_: next(answers)), \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop({}), 0)
        screen = out.getvalue()
        self.assertIn("orchestrator  worker  effort", screen)
        self.assertIn("you talk to one orchestrator", screen)
        self.assertIn("not a key: 'r'", screen)

    def test_fresh_cleanup_keeps_remote(self):
        cleanup = between(FRESH, 'cleanup() {', '\ntrap cleanup EXIT')
        self.script("gh", 'echo "$*" >>"$WORK/gh-calls"\nexit 97\n')
        self.shell('''sync_back() { :; }
smoke_lock_drop() { :; }
cleanup_logs() { :; }
KEEP=0 SMOKE_REPO=fixture/repo
E2E_TMUX_DIR="$TMUX_TMPDIR"
''' + cleanup + '\ncleanup', check=True)
        self.assertFalse((self.root / 'gh-calls').exists())

    def test_fresh_cleanup_removes_work_and_retains_only_latest_failure_archive(self):
        cleanup = between(FRESH, 'cleanup_logs()', '\ncleanup()')
        archive = self.home / '.agentkit/tmp/e2e-fresh-failure.tar.gz'
        for number, code in enumerate((0, 1, 2, 0)):
            work = self.root / f'gate-{number}'
            work.mkdir()
            (work / 'failure.log').write_text(f'gate {number}')
            for secret in ('phone', 'phone.pub', 'ghenv', 'source.bundle'):
                (work / secret).write_text('fixture secret')
            result = self.shell('''say() { echo "$*"; }
INVOKER=fixture INVHOME="$HOME"
''' + cleanup + f'\ncleanup_logs {code}', env={"WORK": str(work)}, check=True)
            self.assertFalse(work.exists())
            if code:
                self.assertIn(f'failure logs: {archive}', result.stdout)
                self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
                with tarfile.open(archive) as saved:
                    self.assertEqual(saved.getnames(), ['.', './failure.log'])
                    self.assertEqual(saved.extractfile('./failure.log').read().decode(), f'gate {number}')
            elif number == 0:
                self.assertFalse(archive.exists())
        self.assertEqual(list(archive.parent.glob('e2e-fresh*')), [archive])
        before = archive.read_bytes()
        work = self.root / 'failed-archive'
        work.mkdir()
        self.script('tar', 'echo "fixture archive failure" >&2; exit 29\n')
        result = self.shell('''say() { echo "$*"; }
INVOKER=fixture INVHOME="$HOME"
''' + cleanup + '\ncleanup_logs 1', env={"WORK": str(work)}, check=True)
        self.assertIn('WARN could not archive', result.stdout)
        self.assertFalse(work.exists())
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual(list(archive.parent.glob('e2e-fresh*')), [archive])

    def test_fresh_source_is_the_committed_branch_and_remote_presence_is_not_done(self):
        source = between(FRESH, 'SOURCE_SHA=', 'IRC=$?')
        self.shell(self.newrepo + '''
SOURCE=$(newrepo source)
# The installer itself is a fixture; no package, account or network operation can run.
printf 'git rev-parse HEAD >installed-revision\n' >"$SOURCE/install.sh"
git -C "$SOURCE" add .; git -C "$SOURCE" commit -qm installer
git -C "$SOURCE" checkout -qb branch-under-test
printf 'branch revision\\n' >"$SOURCE/branch-only"
git -C "$SOURCE" add .; git -C "$SOURCE" commit -qm branch
as() { bash -c "$1"; }
INVOKER=fixture REPO="$SOURCE"
''' + source + '''
test -f "$HOME/agentkit/branch-only"
test "$(cat "$HOME/agentkit/installed-revision")" = "$SOURCE_SHA"
''', check=True)
        # A dirty worktree cannot be certified by the older committed bundle.
        result = self.shell('''INVOKER=fixture REPO="$WORK/source"
printf dirty >"$REPO/branch-only"
''' + source)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('commit the worktree before testing revision', result.stdout)
        # A real local remote with hello.py present but broken. The verifier must fetch past
        # an older, passing local main and run the actual task, not inspect ls-tree output.
        task = self.root / 'task.md'
        task.write_text('## Done when\n```bash\npython3 -c "from hello import hello; assert hello() == \'hello\'"\n```\n')
        self.shell(self.newrepo + '''
TARGET=$(newrepo target)
printf 'def hello(): return "hello"\\n' >"$TARGET/hello.py"
git -C "$TARGET" add .; git -C "$TARGET" commit -qm passing
git init -q --bare -b main "$WORK/origin.git"
git -C "$TARGET" remote add origin "$WORK/origin.git"
git -C "$TARGET" push -q -u origin main
git clone -q "$WORK/origin.git" "$WORK/clone"
printf 'def hello(): return "wrong"\\n' >"$TARGET/hello.py"
git -C "$TARGET" commit -qam broken
git -C "$TARGET" push -q origin main
''', check=True)
        result = self.shell('checked "$WORK/delivery.log" python3 "$REPO/tests/verify_delivery.py" "$WORK/clone" "$WORK/task.md" "$WORK/delivered"')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue((self.root / 'delivered/hello.py').is_file())
        self.assertIn('AssertionError', result.stdout)
        self.assertIn('delivered revision:', (self.root / 'delivery.log').read_text())
        self.assertIn('[exit 1]', (self.root / 'delivery.log').read_text())


if __name__ == '__main__':
    unittest.main()
