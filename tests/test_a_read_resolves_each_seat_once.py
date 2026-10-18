"""A read of the main screen resolves each seat its runs name once, however many seats it lists.

Each seat's tasks were found by filtering every run by the seat it was launched from, following
that seat's renames by reading its record: one read per run per seat listed, some 44,000 on a
host with 3,600 runs and a dozen seats, about a second a read, and the menu back from a seat
waited on it.  A seat's own runs in the look's pass were found the same way.  Offline: a
temporary HOME, fake run records, no tmux.
"""

from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, transitions, watch  # noqa: E402

SEATS = ["acme-api", "acme-docs", "acme-web", "acme-ops"]
NOW = 1_800_000_000


def run(n, seat, **state):
    return Path(f"r{n}"), {"run_id": f"r{n}", "launched_session": seat, "state": "running",
                           "step": "executor", "started_at": NOW - 600, **state}


class ReadResolvesEachSeatOnce(Sandbox):
    def records(self, many=40):
        """Runs from three seats and from a name `acme-ops` had before its rename, which leaves
        a pointer behind in the old name's record, in turn."""
        config.STATE.mkdir(parents=True, exist_ok=True)
        config.session_path("acme-old").write_text(json.dumps({"renamed": "acme-ops"}))
        names = ["acme-api", "acme-docs", "acme-web", "acme-old"]
        return [run(n, names[n % 4]) for n in range(many)]

    def read(self, records):
        """(how many times a read resolved a seat's name, each seat's tasks)."""
        resolved, real = [], config.resolve_session

        def resolve(name):
            resolved.append(name)
            return real(name)
        with patch.object(config, "resolve_session", side_effect=resolve):
            _groups, infos, _needing, _silent = menu.v5o_groups(
                self.cfg, [{"name": seat} for seat in SEATS], records, now=NOW, look=False)
        return len(resolved), {info["name"]: len(info["tasks"]) for info in infos}

    def test_a_read_resolves_as_often_over_ten_times_the_runs(self):
        few, tasks = self.read(self.records())
        self.assertEqual(tasks, dict.fromkeys(SEATS, 10), "a renamed seat lost its runs")
        many, tasks = self.read(self.records(400))
        self.assertEqual(tasks, dict.fromkeys(SEATS, 100))
        self.assertEqual(many, few, "a read resolves a seat's name for every run")

    def test_a_seats_own_runs_resolve_each_name_once_and_leave_out_a_looping_rename(self):
        records = self.records()
        config.session_path("acme-loop").write_text(json.dumps({"renamed": "acme-loop-2"}))
        config.session_path("acme-loop-2").write_text(json.dumps({"renamed": "acme-loop"}))
        records.append(run(40, "acme-loop"))
        resolved = []
        real = config.resolve_session

        def resolve(name):
            resolved.append(name)
            return real(name)
        with patch.object(config, "resolve_session", side_effect=resolve):
            mine = watch.own_runs("acme-ops", records)
        self.assertEqual([state["run_id"] for _, state in mine],
                         [f"r{n}" for n in range(3, 40, 4)])
        self.assertEqual(sorted(resolved),
                         ["acme-api", "acme-docs", "acme-loop", "acme-old", "acme-web"])
        self.assertNotIn(None, transitions.runs_by_seat(records), "a run launched from none")


if __name__ == "__main__":
    unittest.main()
