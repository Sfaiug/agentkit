"""Workers do not make hand-made tmux sessions seats; all processes and delivery are fake."""

from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch


class WorkerPaneNoSeat(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-worker-pane-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.toml").write_text(
            '[launch]\nprograms = ["acme-bin-*"]\n')
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AK_RUN_ROLE": "seat", "AGENTKIT_SESSION": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", config.ADAPTER_DIR_ENV: str(adapters),
            "AK_NOTIFY_SINK": "dry-run"}))
        config.ensure_dirs()
        self.cfg = config.load()
        self.name = "acme-merge"
        self.mark = ""
        self.panes = [101]
        self.table = {101: (1, ["bash"]),
                      102: (101, ["python3", "bin/ak", "run", "merge", "fix-api"]),
                      103: (102, ["/opt/acme/acme-bin-test", "--headless"])}
        self.environ = {103: b"HOME=/fake\0AK_RUN_ROLE=worker\0"}
        self.env_reads = []
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.ps = self.stack.enter_context(patch.object(
            orch.subprocess, "run", side_effect=self.processes))
        read_bytes = Path.read_bytes

        def read(path):
            if str(path).startswith("/proc/"):
                self.assertEqual(path.name, "environ")
                pid = int(path.parent.name)
                self.env_reads.append(pid)
                value = self.environ[pid]   # any non-harness read fails, without touching /proc
                if isinstance(value, OSError):
                    raise value
                return value
            return read_bytes(path)

        self.stack.enter_context(patch.object(Path, "read_bytes", read))
        self.http = self.stack.enter_context(patch.object(
            notify.urllib.request, "urlopen", side_effect=lambda *a, **kw: io.BytesIO(b"{}")))
        orch._PROCESSES.clear()
        self.addCleanup(orch._PROCESSES.clear)

    def processes(self, argv, **kwargs):
        self.assertEqual(argv, ["ps", "-A", "-ww", "-o", "pid=", "-o", "ppid=", "-o", "args="])
        return subprocess.CompletedProcess(argv, 0, "\n".join(
            f"{pid} {parent} {' '.join(words)}" for pid, (parent, words) in self.table.items()))

    def tmux(self, *args, socket=None, **_kw):
        if socket == "":
            self.assertEqual(args[0], "list-sessions")
            return 1, "no server running"
        self.assertIsNone(socket)
        if args[0] == "list-sessions":
            return 0, f"{self.name}\t{self.root}\t100\t0\t{self.mark}"
        if args[0] == "list-panes":
            self.assertEqual(args[:3], ("list-panes", "-a", "-F"))
            if args[3] == "#{session_name}\t#{pane_pid}\t#{pane_dead}":
                return 0, "\n".join(f"{self.name}\t{pid}\t0" for pid in self.panes)
            self.assertEqual(args[3], "#{session_name}\t#{pane_dead}")
            return 0, f"{self.name}\t0"
        self.assertEqual(args, ("has-session", "-t", f"={self.name}"))
        return 0, ""

    def listed(self):
        return [seat["name"] for seat in orch.listing(reconcile=False)]

    def test_worker_only_session_has_no_row_card_or_count(self):
        self.assertEqual(orch.sessions(), [])
        self.assertEqual(self.listed(), [])
        self.assertIsNone(orch.find(self.name))
        with patch.object(notify, "transition") as transition:
            notify.tick_cards(log=lambda _: None)
        transition.assert_not_called()
        self.http.assert_not_called()
        self.assertFalse(config.card_path(self.name).exists())
        self.assertEqual(set(self.env_reads), {103})

    def test_same_session_with_an_interactive_harness_is_a_seat(self):
        self.table[103] = (102, ["/opt/acme/acme-bin-test"])
        for env in (b"HOME=/fake\0", b"AK_RUN_ROLE=seat\0"):
            with self.subTest(env=env):
                self.environ[103] = env
                self.assertEqual(self.listed(), [self.name])
                with patch.object(notify, "transition") as transition:
                    notify.tick_cards(log=lambda _: None)
                self.assertEqual([call.args[0] for call in transition.call_args_list], [self.name])

    def test_worker_descendants_cannot_make_a_seat_even_without_the_marker(self):
        self.table.update({104: (103, ["bash"]), 105: (104, ["acme"])})
        self.environ[105] = b"AK_RUN_ROLE=seat\0"
        self.assertEqual(self.listed(), [])
        self.assertEqual(self.env_reads, [103])

    def test_worker_as_the_pane_process_is_not_a_seat(self):
        self.panes = [103]
        self.assertEqual(self.listed(), [])

    def test_an_independent_interactive_harness_still_makes_a_seat(self):
        for parent in (101, 201):
            with self.subTest(parent=parent):
                self.panes = [101] if parent == 101 else [101, 201]
                self.table.update({201: (1, ["bash"]), 202: (parent, ["bash", "-e", "/opt/acme"])})
                self.environ[202] = b"AK_RUN_ROLE=seat\0"
                with orch.one_reading():
                    self.assertEqual(self.listed(), [self.name])

    def test_a_worker_under_a_marked_or_recorded_seat_leaves_it_a_seat(self):
        for ownership in ("mark", "record"):
            with self.subTest(ownership=ownership):
                self.mark = "1" if ownership == "mark" else ""
                if ownership == "record":
                    config.save_session(self.cfg, self.name, "fable", ["opus"],
                                        {"cwd": str(self.root)})
                self.assertEqual(self.listed(), [self.name])
        self.ps.assert_not_called()
        self.assertEqual(self.env_reads, [])

    def test_unreadable_environment_keeps_the_harness_a_seat(self):
        for error in (PermissionError(), FileNotFoundError()):
            with self.subTest(error=type(error).__name__):
                self.environ[103] = error
                self.assertEqual(self.listed(), [self.name])

    def test_only_the_exact_worker_environment_entry_excludes_a_harness(self):
        self.environ[103] = b"OTHER_AK_RUN_ROLE=worker\0AK_RUN_ROLE=worker-helper\0"
        self.assertEqual(self.listed(), [self.name])

    def test_an_existing_worker_only_card_closes_once_with_one_ps_per_tick(self):
        url = "https://discord.invalid/api/webhooks/1/acme"
        pending = {"message_id": "4242", "webhook": hashlib.sha256(url.encode()).hexdigest(),
                   "embed": {"title": f"Needs you · {self.name}",
                             "fields": [{"name": "open", "value": "press 1"}]}}
        config.card_path(self.name).write_text(json.dumps({
            "word": "needs you", "since": 100, "episode": "acme-episode", "sent": True,
            "open_needs": [pending]}))
        with patch.object(notify, "webhook", return_value=url), \
                patch.object(notify, "transition") as transition, \
                patch.object(orch, "AGENT_LOOK_EVERY", 0):
            notify.tick_cards(log=lambda _: None)
            self.assertEqual(self.ps.call_count, 1)
            notify.tick_cards(log=lambda _: None)
            self.assertEqual(self.ps.call_count, 2)
        transition.assert_not_called()
        self.http.assert_called_once()
        request = self.http.call_args.args[0]
        self.assertEqual((request.method, request.full_url), ("PATCH", url + "/messages/4242"))
        payload = json.loads(request.data)
        self.assertEqual(payload["embeds"][0], {"title": f"Answered · {self.name}"})
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertFalse(config.card_path(self.name).exists())


if __name__ == "__main__":
    unittest.main()
