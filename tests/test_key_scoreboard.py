"""`ak run status --history` ends with the scoreboard: its pinned rows in their order, an empty
one saying so in words, and the runs on ak itself counted in the `ak` row as cost, never among
the products.

The owner judges ak week by week from this board (AGENTS.md, Owner rules), so its rows and their
order are pinned.  Work on ak itself is
what ak costs, not what it delivers: a run on a repository named as the checkout ak runs from
counts in the `ak` row, with its share of every token the week's runs reported, and not in
`products`.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on projects from gitrig.py, with scripted harnesses from
fakeadapter.py whose turns report their tokens in their event logs, as an adapter's do.
"""

import json
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import AK, Home
from fixtures.gitrig import Rig

TITLE = "Scoreboard (reported tokens; size now and 7 days ago)"
LABELS = ["products", "ak", "tokens", "intent", "owner", "built", "waits", "merged", "parks", "sunk",
          "broke", "ak size"]
# The host's own load never holds a run back or shows in the header: its readings are a roomy
# machine's.
ROOMY = json.dumps({"free_mb": 8192, "mem_total_mb": 16384, "load": 0, "cpus": 4})
# The Home's notify sink marks every run a test suite's, which ak never records: these runs go
# without it, as the owner's, and with no webhook configured nothing is posted anywhere.
OWNERS = {"AK_NOTIFY_SINK": None}
# A turn's event log is in its <out>, the fifth argument after `run` (`config.adapter`);
# the wrapped fake's own turn runs first, untouched.
REPORTING = """#!/bin/sh
{turn} "$@"
code=$?
if [ "$1" = run ]; then cp {events} "$6/events.jsonl"; fi
exit $code
"""
EVENT = {"claude": "result", "codex": "turn.completed"}


def scoreboard(out):
    """Each row of the board as printed, in order: its label and its two weeks' cells, a cell's
    wrapped lines joined.  Columns are where the heading puts its two weeks."""
    lines = out.splitlines()
    at = lines.index(TITLE)
    heading = lines[at + 1]
    now, before = heading.index("last 7 days"), heading.index("7 days before")
    rows = []
    for line in lines[at + 2:]:
        if line[now - 2:now].strip() or line[before - 2:before].strip():
            break       # past the table: the lines sizing each repository's tasks
        if line[:now].strip():
            rows.append((line[:now].strip(), [], []))
        for cell, text in zip(rows[-1][1:], (line[now:before].strip(), line[before:].strip())):
            if text:
                cell.append(text)
    return [(label, " ".join(this), " ".join(last)) for label, this, last in rows]


class AnEmptyBoard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.env["AK_HOST_READINGS"] = ROOMY
        cls.done = cls.home.ak("run", "status", "--history")

    def test_it_shows_every_pinned_row_in_order_under_its_two_weeks(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        lines = self.done.out.splitlines()
        self.assertIn(TITLE, lines)
        heading = lines[lines.index(TITLE) + 1]
        self.assertLess(heading.index("last 7 days"), heading.index("7 days before"))
        self.assertEqual([label for label, _, _ in scoreboard(self.done.out)], LABELS)

    def test_a_row_with_nothing_to_show_says_so_in_words(self):
        empty = {"products": "no runs ended", "ak": "no runs ended",
                 "tokens": "no tokens recorded", "intent": "not recorded",
                 "owner": "not recorded", "built": "no runs ended", "waits": "not recorded",
                 "merged": "no merged change", "parks": "not recorded",
                 "sunk": "no tokens recorded", "broke": "no merged change"}
        rows = {label: (this, last) for label, this, last in scoreboard(self.done.out)}
        for label, words in empty.items():
            with self.subTest(label):
                self.assertEqual(rows[label], (words, words))

    def test_its_machine_form_is_an_empty_json_list(self):
        done = self.home.ak("run", "status", "--history", "--json")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(done.out), [])


class WorkOnAkItself(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.env["AK_HOST_READINGS"] = ROOMY
        # named as the checkout the program runs from, as bin/ak finds its own
        own, acme = Rig(cls.home, Path(AK).resolve().parents[1].name), Rig(cls.home, "acme")
        akconfig.write(cls.home, ["opus", "astra"])
        fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        events = {harness: report_tokens(fake) for harness, fake in fakes.items()}
        # 1,000 tokens on ak itself, 3,000 on acme: ak's share of the week's is a quarter
        cls.tokens = {own.name: {"claude": (500, 100), "codex": (300, 100)},
                      "acme": {"claude": (2000, 400), "codex": (500, 100)}}
        for rig, title in ((own, "Add retry file"), (acme, "Add retry note")):
            for harness, (given, made) in cls.tokens[rig.name].items():
                events[harness].write_text(json.dumps({"type": EVENT[harness], "usage": {
                    "input_tokens": given, "output_tokens": made}}) + "\n")
            done = cls.home.ak("run", str(taskfile.write(cls.home, rig.path, title)),
                               "--no-merge", env=OWNERS, timeout=300)
            assert done.code == 0, done.out + done.err
        cls.done = cls.home.ak("run", "status", "--history")

    def test_a_run_on_ak_itself_counts_in_the_ak_row_and_not_in_products(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        rows = {label: (this, last) for label, this, last in scoreboard(self.done.out)}
        products, ak = rows["products"], rows["ak"]
        self.assertTrue(products[0].startswith("1 runs ended;"), products)
        self.assertTrue(ak[0].startswith("1 runs ended;"), ak)
        self.assertEqual((products[1], ak[1]), ("no runs ended", "no runs ended"))

    def test_the_ak_row_gives_its_share_of_every_recorded_token(self):
        rows = {label: (this, last) for label, this, last in scoreboard(self.done.out)}
        self.assertTrue(rows["ak"][0].endswith("; 25% of all recorded tokens"), rows["ak"])
        self.assertNotIn("recorded tokens", rows["products"][0])

    def test_the_machine_form_keeps_the_tokens_each_turn_reported(self):
        done = self.home.ak("run", "status", "--history", "--json")
        self.assertEqual(done.code, 0, done.err)
        spent = {Path(row["repo"]).name: (row["executor_tokens"], row["reviewer_tokens"])
                 for row in json.loads(done.out)}
        self.assertEqual(spent, {repo: tuple(sum(made[harness]) for harness in ("claude", "codex"))
                                 for repo, made in self.tokens.items()})


def report_tokens(fake):
    """Wrap a fake harness so each of its turns leaves, as its event log, the event in the file
    returned, written before the turn."""
    turn = fake.script.with_name(f"{fake.harness}-turn.sh")
    fake.script.rename(turn)
    events = fake.dir / f"{fake.harness}.events"
    fake.script.write_text(REPORTING.format(turn=shlex.quote(str(turn)),
                                            events=shlex.quote(str(events))))
    fake.script.chmod(0o755)
    return events


if __name__ == "__main__":
    unittest.main()
