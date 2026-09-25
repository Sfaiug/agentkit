"""v5z: every listing outside the menu wears the same design; offline.

Fixed fake state -- three runs (working, unfinished, done merged) and two
seats -- through the real renderers. COLUMNS is set and there is no tty, so
the output is plain text with UTF-8 glyphs and the clock is pinned.

`python3 tests/test_v5z.py --fixtures` re-renders the three fixtures for
review by eye; the tests below pin them byte for byte.
"""

from contextlib import redirect_stdout
import io
import json
import os
import re
import shutil
import sys
import time
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import command_help, config, menu, orch, run, terminal

NOW = 1_800_000_000      # what every draw reads as the time
DAY = 86400
WORKING_ID = "20260101-0900-ship-the-tally"
UNFINISHED_ID = "20260101-0830-fix-the-parser"
DONE_ID = "20260101-0700-write-release-notes"
WORKING_TITLE = "Ship the tally so every seat row says what the run has done"
FIGURE_ONLY = re.compile(r"(?m)^\s*[\d/…]+\s*$")   # a line holding only a figure
SLICE_LINE = "slice agentkit.slice · 12 tasks · 30% of its ceiling"   # `ak orch list`'s last


class Listings(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        self.stack.enter_context(patch.object(menu.time, "strftime", return_value="14:02"))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                      {"state": seat.get("live", "working"), "rule": "fixture",
                                       "evidence": "", "began": seat.get("since"),
                                       "since": seat.get("since")}))
        atoll_repo = str(config.CODE / "atoll")
        self.seats = [
            {"name": "atoll", "repo": atoll_repo, "path": "/tmp/atoll-checkout",
             "live": "working", "since": NOW - 120, "created": NOW - 5 * DAY},
            {"name": "scribe", "repo": None, "path": "/tmp/scribe",
             "live": "at_prompt", "since": NOW - 3600, "created": NOW - 3600},
        ]
        config.save_session(self.cfg, "atoll", "fable", ["opus", "astra"],
                            {"repo": atoll_repo, "cwd": atoll_repo})
        config.save_session(self.cfg, "scribe", "astra", ["spark", "opus", "fable", "astra"],
                            {"repo": None, "cwd": str(self.root)})
        present = config.WT / "20260101-0900-ship-the-tally"
        present.mkdir(parents=True)
        self.working = self.state(WORKING_ID, owner="atoll", title=WORKING_TITLE,
                                  state="running", executor="opus", reviewer="astra",
                                  rounds=3, round_summaries=[{}], started_at=NOW - 420,
                                  finished_at=None, worktree=str(present),
                                  **run.process_owner())
        self.unfinished = self.state(UNFINISHED_ID, owner=None, title="Fix the parser",
                                     state="interrupted", executor="opus", reviewer="astra",
                                     rounds=2, round_summaries=[], started_at=NOW - 3600,
                                     finished_at=None, interrupted_at=NOW - 1800,
                                     interruption_reason="Run process exited.",
                                     recovery_pending=True, recovery_notified="needs")
        self.done = self.state(DONE_ID, owner="atoll", title="Write release notes",
                               state="pass", verdict="PASS", merged=True,
                               executor="opus", reviewer="astra", rounds=2,
                               round_summaries=[{}, {}], started_at=NOW - 7200,
                               finished_at=NOW - 3600,
                               worktree=str(config.WT / "20260101-0700-gone"))

    def state(self, name, owner, **extra):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "launched_session": owner, **extra}
        run.save_state(directory, state)
        return directory

    def tallies(self):
        return run.seat_tallies(state for _, state in menu.run_records())

    def status(self, argv, width=100):
        # Alive readings are pinned: the working run holds three processes, the
        # interrupted one holds none, and the real RSS of this test process is
        # never what a byte-for-byte fixture compares against.
        def alive(state, *args, **kwargs):
            if state.get("run_id") == WORKING_ID:
                return (3, 1288490189)
            if state.get("run_id") == UNFINISHED_ID:
                return (0, 0)
            return None
        with patch.object(terminal, "width", return_value=width), \
                patch.object(run, "scope_alive", side_effect=alive), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status(list(argv)), 0)
        return out.getvalue()

    def orch_list(self, argv, width=100):
        # the last line says which slice the agents run in, and what it says depends on the
        # host; this is a test of the layout, so it is pinned to one sentence
        with patch.object(orch, "listing", return_value=self.seats), \
                patch.object(orch, "slice_line", return_value=SLICE_LINE), \
                patch.object(terminal, "width", return_value=width), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.cmd_list(list(argv)), 0)
        return out.getvalue()

    def orch_table(self, width):
        return orch.list_table(self.seats, self.cfg, self.tallies(), width)

    def test_v5z_a_menu_has_no_runs_screen(self):
        self.assertFalse(hasattr(menu, "runs_listing"))
        self.assertFalse(hasattr(menu, "runs"))
        self.assertFalse(hasattr(menu, "recover_run"))
        self.assertFalse(hasattr(menu, "watch_run"))
        self.assertNotIn("r runs", menu.KEYS)
        answers = iter(["r", "q"])
        with patch.object(orch, "listing", return_value=self.seats), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "read", side_effect=lambda *_: next(answers)), \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        self.assertIn("not a key: 'r'", out.getvalue())
        # `ak run status` is where runs are listed now.
        table = self.status([])
        self.assertIn("! needs you", table)
        self.assertIn(WORKING_ID, table)

    def test_v5z_d_run_status_table_and_paths_only_for_one_id_or_why(self):
        table = self.status([])
        self.assertEqual(table, (REPO / "tests/fixtures/v5z-status.txt").read_text())
        for token in ("result:", "record:", "workspace:", "continue:"):
            self.assertNotIn(token, table)
        self.assertIn("! needs you", table)
        one = self.status([UNFINISHED_ID])
        self.assertIn(f"  result: {config.RUNS / UNFINISHED_ID}/result.md", one)
        self.assertIn(f"  record: {config.RUNS / UNFINISHED_ID}/run.json", one)
        self.assertNotIn("workspace:", one)   # it records none
        merged = self.status([DONE_ID])
        self.assertIn("workspace:", merged)
        self.assertIn("removed; branch removed", merged)
        whole = self.status(["--why"])
        self.assertIn("result:", whole)
        self.assertIn("record:", whole)
        # each run's lines sit indented under its own row, never in one block
        positions = [whole.index(name) for name in (WORKING_ID, UNFINISHED_ID, DONE_ID)]
        self.assertEqual(positions, sorted(positions))
        details = [whole.index(f"  result: {config.RUNS / name}/result.md")
                   for name in (WORKING_ID, UNFINISHED_ID, DONE_ID)]
        for row_at, detail_at, next_at in zip(positions, details,
                                              positions[1:] + [len(whole)]):
            self.assertTrue(row_at < detail_at < next_at)

    def test_v5z_e_plain_prints_todays_first_line_byte_for_byte(self):
        directory = config.RUNS / "20260101-0900-plain-check"
        directory.mkdir()
        run.save_state(directory, {"run_id": directory.name, "title": "Plain check",
                                   "state": "pass", "verdict": "PASS", "merged": True,
                                   "executor": "opus", "reviewer": "astra", "branch": "main",
                                   "review": {"executor": "opus", "reviewer": "astra",
                                              "returncode": 0, "verdict": "PASS",
                                              "done_when": True,
                                              "executor_provider": "anthropic",
                                              "reviewer_provider": "codex"},
                                   "rounds": 2, "round_summaries": [{}, {}],
                                   "started_at": NOW - 3600, "finished_at": NOW - 60})
        out = self.status(["--plain", directory.name])
        lines = out.splitlines()
        self.assertEqual(lines[0], "host: 8 cpus · load 1 · 4 G free · "
                                  "a run is admitted while ≥ 3.2 G free and load ≤ 8")
        self.assertEqual(lines[1], "20260101-0900-plain-check" + " " * 16 +
                                    "pass" + " " * 8 + "PASS " + " opus/astra  main  merged")

    def test_v5z_f_json_is_unchanged(self):
        rows = json.loads(self.status(["--json"]))
        self.assertEqual([row["run_id"] for row in rows],
                         [WORKING_ID, UNFINISHED_ID, DONE_ID])
        for row in rows:
            self.assertEqual(row["paths"]["result"],
                             str(config.RUNS / row["run_id"] / "result.md"))
            self.assertEqual(row["paths"]["record"],
                             str(config.RUNS / row["run_id"] / "run.json"))
            self.assertIn("workspace_present", row["paths"])

    def test_v5z_g_orch_list_aligned_and_never_cuts_workers(self):
        screen = self.orch_list([])
        self.assertEqual(screen, (REPO / "tests/fixtures/v5z-orch-list.txt").read_text())
        lines = screen.splitlines()
        self.assertTrue(all(terminal.cells(line) <= 100 for line in lines), screen)
        self.assertEqual(lines[-1], SLICE_LINE)
        rows = lines[1:-1]
        # aligned: the workers and the age start in the same column on every row
        workers = ["opus,astra", "spark,opus,fable,astra"]
        self.assertEqual(len({line.index(text) for line, text in zip(rows, workers)}),
                         1, screen)
        ages = [line.rsplit(None, 1)[-1] for line in rows]
        self.assertEqual(ages, ["5d", "1h"])
        self.assertEqual(len({line.index(age) for line, age in zip(rows, ages)}), 1, screen)
        for worker in ("spark", "opus", "fable", "astra"):
            self.assertIn(worker, screen)
        self.assertIn("spark,opus,fable,astra", screen)   # the whole list, on one line
        self.assertIn("1 running · 1 merged", screen)
        self.assertIn("no runs yet", screen)
        for seat in self.seats:
            self.assertNotIn(seat["path"], screen)   # the checkout path stays off
        why = self.orch_list(["--why"])
        self.assertIn("  path: /tmp/atoll-checkout", why)
        self.assertIn("authority:", why)
        # wrapped, never cut: where one line cannot hold the worker list it
        # rides a continuation, and every name survives whole
        header, groups = self.orch_table(40)
        self.assertEqual(len(groups), 2)
        self.assertTrue(any(len(group) > 1 for group in groups), groups)
        narrow = "\n".join(line for group in groups for line in group)
        names = [word for line in narrow.splitlines()
                 for chunk in line.split() for word in chunk.split(",")]
        for worker in ("spark", "opus", "fable", "astra"):
            self.assertIn(worker, names)
        self.assertNotIn("…", narrow)
        # a wrapped wide row continues under the workers column, the way a
        # wrapped title continues under the title column on the runs screen
        _, wide = self.orch_table(90)
        scribe = next(group for group in wide if "scribe" in group[0])
        self.assertGreater(len(scribe), 1, scribe)
        fields = re.split(r"( {2,})", scribe[0])
        tails = [line.strip() for line in scribe[1:]]
        self.assertEqual(fields[10] + "".join(tails), "spark,opus,fable,astra")
        col = scribe[0].index(fields[10])
        self.assertTrue(all(line.index(tail) == col
                            for line, tail in zip(scribe[1:], tails)), scribe)
        self.assertTrue(all(terminal.cells(line) <= 90 for line in scribe), scribe)

    def test_v5z_h_top_help_is_one_screen(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            text = command_help.render("")
        self.assertEqual(text, (REPO / "tests/fixtures/v5z-help.txt").read_text())
        self.assertTrue(text.startswith("usage: ak ["))
        # the two lists and the commands table stay linked both ways
        listed = [*command_help.ORCHESTRATOR, *command_help.INTERNAL]
        top = [name for name in command_help.COMMANDS if " " not in name]
        self.assertEqual(sorted(listed), sorted(top))
        self.assertEqual(sorted(command_help.PURPOSES), sorted(top))
        for name in command_help.ORCHESTRATOR:
            line = f"  {name.ljust(7)}  {command_help.PURPOSES[name]}"
            self.assertEqual(text.count(line), 1, line)
        internal = next(line for line in text.splitlines() if line.startswith("internal:"))
        self.assertEqual(internal.split()[1:], list(command_help.INTERNAL))
        for name in command_help.INTERNAL:   # no purpose line, no usage text
            self.assertFalse([line for line in text.splitlines() if line.startswith(f"  {name} ")])
        self.assertLessEqual(len(text.splitlines()), 40)
        self.assertIn("Use -h or --help after any command.", text)
        self.assertRegex(text, r"(?m)^Example: ak run task\.md --bg$")
        for command in command_help.COMMANDS:
            own = command_help.render(command)
            self.assertTrue(own.startswith(command_help.purpose(command) + "\n\n"),
                            command)
            self.assertIn(command_help.COMMANDS[command][0].splitlines()[0], own)

    def test_v5z_j_long_ids_keep_the_table_and_cut_the_slug_at_a_word(self):
        long_id = "20260101-0900-this-run-id-is-far-too-long-for-its-own-good"
        directory = config.RUNS / long_id
        directory.mkdir()
        run.save_state(directory, {"run_id": long_id, "title": "Long", "state": "running",
                                   "executor": "opus", "reviewer": "astra", "rounds": 3,
                                   "round_summaries": [{}, {}],
                                   "started_at": NOW - 420, "finished_at": None,
                                   **run.process_owner()})
        table = self.status([])
        header = table.splitlines()[1]
        for column in ("id", "title", "state", "worker", "round", "age"):
            self.assertIn(column, header)
        row = next(line for line in table.splitlines() if "Long" in line.split())
        self.assertIn("20260101 0900 this-run-id-is-far-too…", row)
        self.assertNotIn("20260101-0900-this-run", row)   # the slug, cut at a word
        self.assertIn("Long", row.split())   # the title keeps its floor first
        id_cell = row.split("  ")[0]
        self.assertTrue(id_cell.endswith("…"))   # the cell holds its ellipsis
        self.assertLessEqual(terminal.cells(id_cell), 40)
        self.assertTrue(all(terminal.cells(line) <= 100 for line in table.splitlines()))

    def test_v5z_k_empty_status_prints_the_line_and_exits_zero(self):
        header, groups = run.status_rows([], 100)
        self.assertEqual(groups, [])
        self.assertIn("id", header)
        for name in (WORKING_ID, UNFINISHED_ID, DONE_ID):
            shutil.rmtree(config.RUNS / name)
        for argv in ([], ["--history"], ["--why"]):
            out = self.status(argv)
            self.assertIn("no current runs", out)
        # --why with no rows is the same answer, not a bare header
        self.assertNotIn("title", self.status(["--why"]))

    def test_v5z_l_orch_list_has_a_narrow_layout(self):
        for width in (40, 60):
            screen = self.orch_list([], width=width)
            lines = screen.splitlines()
            self.assertTrue(all(terminal.cells(line) <= width for line in lines),
                            screen)
            self.assertNotIn("…", screen)
            self.assertIn("name", lines[0])
            self.assertIn("project", lines[0])
            for worker in ("spark", "opus", "fable", "astra"):
                self.assertIn(worker, screen)
            # the whole worker list rides continuations, every name whole
            self.assertIn("spark,opus,fable,astra", screen)

    def test_v5z_m_exhausted_run_says_what_it_waits_for(self):
        waiting_id = "20260101-0600-wait-for-a-window"
        directory = config.RUNS / waiting_id
        directory.mkdir()
        run.save_state(directory, {"run_id": waiting_id, "title": "Wait for a window",
                                   "state": "exhausted", "quota_dry": True,
                                   "error": "provider quota spent",
                                   "executor": "opus", "reviewer": "astra",
                                   "rounds": 2, "round_summaries": [],
                                   "started_at": NOW - 3600, "finished_at": None,
                                   **run.process_owner()})
        state = run.read_state(directory)
        # no quota run waits on a window: the row keeps the state word, and with
        # nothing to resume it the run is his
        self.assertEqual(run.waiting({**state, "quota_dry": False}), "")
        self.assertEqual(menu.run_state_word({**state, "quota_dry": False}), "needs you")
        self.assertEqual(run.waiting({"state": "running"}), "")
        # the sandbox's empty usage cache leaves a spent window with no known
        # hour, straight through the real reader: nobody needs to act on it
        sentence = run.waiting(state)
        self.assertTrue(sentence.startswith("waiting"), sentence)
        # the column keeps a STATES word; the provider and the hour live on
        # the note line only, said once, never twice on adjacent lines.
        # A run that resumes itself is still working, on `r` and on `ak run status`.
        self.assertEqual(menu.run_state_word(state), "working")
        self.assertEqual(menu.runs_word(state), "working")
        _, blocks = menu._runs_table([(directory, state)], 100, 30)
        block = "\n".join(blocks[0])
        self.assertEqual(block.count(sentence), 1, block)
        self.assertIn("● working", blocks[0][0])
        self.assertNotIn("unfinished", block)
        self.assertNotIn(sentence, blocks[0][0])
        self.assertNotIn("offers resume", block)
        # one shape for every note: glyph, then what the number is for
        self.assertIn(f"● {sentence}", block)
        # ak run status reads the same word from the same table
        table = self.status([])
        row = next(line for line in table.splitlines()
                   if "Wait for a window" in line)
        self.assertIn("● working", row)
        self.assertNotIn(sentence, row)
        one = self.status([waiting_id])
        self.assertIn(sentence, one)
        self.assertNotIn("offers recovery", one)
        # --plain keeps today's words for the scripts that read it
        plain = self.status(["--plain", waiting_id])
        self.assertIn(f"ak run resume {waiting_id} offers recovery", plain)

    def test_v5z_n_own_help_prints_the_purpose_once(self):
        same = command_help._same_sentence
        for command in command_help.COMMANDS:
            own = command_help.render(command)
            first = command_help.COMMANDS[command][1].splitlines()[0]
            # the purpose line may survive as the purpose itself, never twice
            self.assertLessEqual(own.count(first), 1, command)
            if same(first, command_help.purpose(command)):
                self.assertNotIn(first, own.splitlines()[1:], command)
        for name in ("usage", "worker", "browser", "macbridge", "notify"):
            own = command_help.render(name)
            self.assertEqual(own.count(command_help.PURPOSES[name]), 1, name)

    def test_v5z_o_waiting_runs_read_the_cache_and_config_once_per_draw(self):
        pairs = []
        for hour in ("0600", "0610"):
            waiting_id = f"20260101-{hour}-wait-for-a-window"
            directory = config.RUNS / waiting_id
            directory.mkdir()
            run.save_state(directory, {"run_id": waiting_id, "title": "Wait for a window",
                                       "state": "exhausted", "quota_dry": True,
                                       "error": "provider quota spent",
                                       "executor": "opus", "reviewer": "astra",
                                       "rounds": 2, "round_summaries": [],
                                       "started_at": NOW - 3600, "finished_at": None,
                                       **run.process_owner()})
            pairs.append((directory, run.read_state(directory)))
        with patch.object(run, "_cached_providers",
                          wraps=run._cached_providers) as cached, \
                patch.object(config, "load", wraps=config.load) as loaded:
            _, blocks = menu._runs_table(pairs, 100, 30)
            self.assertEqual(cached.call_count, 1, "one cache read per draw")
            self.assertEqual(loaded.call_count, 1, "one config read per draw")
        for block in blocks:
            self.assertIn("waiting for a provider window", "\n".join(block))
        # a caller handing the scope down reads nothing further
        with patch.object(run, "_cached_providers",
                          wraps=run._cached_providers) as cached:
            lines = run.status_details(pairs[0][0], pairs[0][1], {}, None)
            self.assertEqual(cached.call_count, 0)
        self.assertIn("waiting for a provider window", "\n".join(lines))

    def test_v5z_p_table_cells_pad_outside_the_colour_escapes(self):
        # cut, then style, then pad: no pad space may sit inside an escape,
        # and the row keeps no trailing space colour could hide
        with patch.object(terminal, "colour_depth", return_value=8):
            line = terminal.table_row(["#", "title", "state"], [2, 8, 7],
                                      "", ["dim"] * 3)
        self.assertNotIn(" \033[0m", line)
        self.assertIn("\033[0m   ", line)
        self.assertTrue(line.endswith("\033[0m"))
        self.assertEqual(line, line.rstrip())
        self.assertEqual(terminal.cells(line), 2 + 2 + 8 + 2 + 5)

    def test_v5z_q_wrapped_workers_keep_their_separator(self):
        # a continued chunk keeps its trailing comma, so the pieces rejoin to
        # the list exactly and no chunk outgrows the room
        chunks = orch._wrap_workers("opus,astra,spark,fable,comet,flash", 20)
        self.assertEqual("".join(chunks), "opus,astra,spark,fable,comet,flash")
        self.assertTrue(all(terminal.cells(chunk) <= 20 for chunk in chunks))
        self.assertTrue(chunks[0].endswith(","))
        self.assertFalse(chunks[-1].endswith(","))
        self.assertGreater(len(chunks), 1)
        # a list that fits stays one bare chunk, comma or not
        self.assertEqual(orch._wrap_workers("spark,opus,fable,astra", 100),
                         ["spark,opus,fable,astra"])
        self.assertEqual(orch._wrap_workers("?", 100), ["?"])

    def test_v5z_r_an_ending_its_orchestrator_has_never_reads_needs_you(self):
        repo = str(config.CODE / "atoll")
        failed = dict(state="fail", verdict="FAIL", executor="opus", reviewer="astra",
                      rounds=2, round_summaries=[{}, {}], repo=repo,
                      started_at=NOW - 7200, finished_at=NOW - 3600)
        settled = {"20260101-0600-handed-back": {"handed_back": NOW - 3500},
                   "20260101-0601-hand-back-pending": {"handback_pending": True},
                   "20260101-0602-acknowledged": {"recovery_acknowledged_at": NOW - 3500},
                   "20260101-0603-replaced": {"title": "Replaced by a merged run"},
                   "20260101-0604-relaunched": {"branch": "ak/relaunched"},
                   "20260101-0605-blocked": {"state": "blocked", "verdict": "BLOCKED",
                                             "error": "the checks are wrong",
                                             "handed_back": NOW - 3500}}
        for name, extra in settled.items():
            self.state(name, owner="atoll", **{**failed, "title": name, **extra})
        self.state("20260101-0610-merged", owner="atoll", **{
            **failed, "title": "Replaced by a merged run", "state": "pass", "verdict": "PASS",
            "merged": True, "started_at": NOW - 3000, "finished_at": NOW - 1800})
        # a relaunch `from:` the branch supersedes whatever its own ending, under any title;
        # the same branch name in another repository is another branch
        continued = self.state("20260101-0611-continued", owner="atoll", **{
            **failed, "title": "Relaunched (continued from its branch)", "from": "ak/relaunched",
            "branch": "ak/relaunched-2", "started_at": NOW - 3000, "finished_at": NOW - 1800})
        self.state("20260101-0612-elsewhere", owner="atoll", **{
            **failed, "title": "Elsewhere", "repo": str(config.CODE / "other"),
            "branch": "ak/relaunched"})
        # a later merge of the smoke suite's own, under a real run's title, replaces nothing
        smoke = self.state("20260101-0613-smoke-make-hello-pass", owner=None, **{
            **failed, "title": "Relaunched (continued from its branch)",
            "state": "pass", "verdict": "PASS", "merged": True, "finished_at": NOW - 600,
            "unattended": True, "repo": str(config.TMP / "smoke-20260101-000000" / "repo-hello")})
        records = [run.read_state(directory) for directory in config.RUNS.iterdir()]
        index = run.supersession_index(records)
        relaunched = run.read_state(config.RUNS / "20260101-0604-relaunched")
        for kwargs in ({"records": records}, {"index": index}):
            self.assertEqual(run.superseded_by(relaunched, **kwargs), continued.name)
            self.assertIsNone(run.superseded_by(run.read_state(
                config.RUNS / "20260101-0612-elsewhere"), **kwargs))
        table = self.status([])
        rows = {name: next(line for line in table.splitlines() if line.startswith(name))
                for name in [*settled, continued.name, "20260101-0612-elsewhere"]}
        for name in settled:
            self.assertIn("✓ done", rows[name], name)
            self.assertNotIn("needs you", rows[name], name)
        self.assertIn("✓ blocked · the checks are wrong", table)
        self.assertIn("! needs you", rows[continued.name])
        self.assertIn("! needs you", rows["20260101-0612-elsewhere"])
        self.assertEqual(table.count("needs you"), 3, table)   # those two and the unfinished
        # the record's own word is still the menu's
        self.assertEqual(menu.run_state_word(relaunched), "needs you")
        # the smoke suite's own run is not listed, and its id still finds it
        self.assertNotIn(smoke.name, table)
        self.assertIn(smoke.name, self.status([smoke.name]))
        # `ak run status <id>` acknowledges the ending it shows as it found it; after that
        # it reads done
        self.assertIn("! needs you", self.status([continued.name]))
        self.assertTrue(run.read_state(continued).get("recovery_acknowledged_at"))
        self.assertIn("✓ done", self.status([continued.name]))

    def test_v5z_s_the_host_line_names_a_count_cap(self):
        gates = "host: 8 cpus · load 1 · 4 G free · a run is admitted while ≥ 3.2 G free and load ≤ 8"
        for limit, tail in (("4", " · at most 4 runs at once"),
                            ("1", " · at most 1 run at once"), ("0", "")):
            with self.subTest(limit=limit), patch.dict(os.environ, {"AK_MAX_RUNS": limit}):
                self.assertEqual(self.status([]).splitlines()[0], gates + tail)
        # the config's own key, with no override
        shipped = (REPO / config.DEFAULT_CONFIG_NAME).read_text()
        (config.HOME / config.CONFIG_NAME).write_text(
            re.sub(r"(?m)^max_runs = 0\b", "max_runs = 2", shipped))
        with patch.dict(os.environ):
            os.environ.pop("AK_MAX_RUNS", None)
            self.assertEqual(self.status([]).splitlines()[0], gates + " · at most 2 runs at once")

    def test_v5z_i_state_words_come_from_terminal_states(self):
        # A run is working, needs you or done, like every session and every project.
        self.assertEqual(menu.run_state_word(run.read_state(self.working)), "working")
        self.assertEqual(menu.run_state_word(run.read_state(self.unfinished)), "needs you")
        self.assertEqual(menu.run_state_word(run.read_state(self.done)), "done")
        self.assertEqual(menu.run_state_word({"state": "fail"}), "needs you")
        self.assertEqual(menu.run_state_word({"state": "error"}), "needs you")
        for word in ("working", "needs you", "done"):
            self.assertIn(word, terminal.STATES)
            self.assertIn(terminal.state_glyph(word), terminal.state_text(word))


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixtures"]:
        test = Listings()
        test.setUp()
        try:
            (REPO / "tests/fixtures/v5z-status.txt").write_text(test.status([]))
            (REPO / "tests/fixtures/v5z-orch-list.txt").write_text(test.orch_list([]))
            (REPO / "tests/fixtures/v5z-help.txt").write_text(command_help.render(""))
        finally:
            test.doCleanups()
    else:
        unittest.main(verbosity=2)
