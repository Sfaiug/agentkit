"""A seat holding a core is not told of a process that spent its CPU time before moving in."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import cores, host, watch


class TheBusiestProcessSpentItsTimeInTheSeat(unittest.TestCase):
    def test_a_sleeping_process_that_moved_in_is_not_named(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        group, proc, clock = root / "agentkit-seat-acme-1a2b3c4d.scope", root / "proc", root / "at"
        group.mkdir()
        owed, state, hz = [], {}, os.sysconf("SC_CLK_TCK")
        for patched in (patch.dict(os.environ, AK_CGROUP_ROOT=str(root), AK_CORES_CLOCK=str(clock)),
                        patch.object(host, "PROC", proc),
                        patch.object(cores.front, "scopes", return_value={group: "acme"}),
                        patch.object(cores.front, "seat_now", return_value="acme"),
                        patch.object(watch, "seat_read", return_value={}),
                        patch.object(watch, "owe_line", side_effect=lambda *owe: owed.append(owe))):
            self.enterContext(patched)
        for at in (0, 180, 360):
            clock.write_text(str(1800000000 + at))
            (group / "cpu.stat").write_text(f"usage_usec {at * 1000000}\n")
            for pid, cpu, born, command in ((101, at, 10000, "bash acme-spinning-wait.sh"),
                                            (102, 1000, 100, "python3 acme-sleeping-helper.py")):
                (proc / str(pid)).mkdir(exist_ok=True, parents=True)
                fields = ["S"] + ["0"] * 10 + [str(cpu * hz)] + ["0"] * 7 + [str(born * hz)]
                (proc / str(pid) / "stat").write_text(f"{pid} (acme) " + " ".join(fields))
                (proc / str(pid) / "cmdline").write_bytes(command.encode() + b"\0")
            (group / "cgroup.procs").write_text("101\n102\n" if at == 360 else "101\n")
            with patch.object(host.time, "clock_gettime", return_value=10000 + at):
                cores.tell(state, lambda line: None)
        self.assertEqual(len(owed), 1, owed)
        self.assertIn("bash acme-spinning-wait.sh", owed[0][2]["line"])


if __name__ == "__main__":
    unittest.main()
