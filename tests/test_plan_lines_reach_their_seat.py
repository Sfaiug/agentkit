"""Every line ak writes into a seat's plan reaches that seat, whatever model or harness runs it.

The tick once wrote a proven switch's line into the plan of a seat at rest (20 Oct 2026):
nothing told the seat, so it read `needs you` with nothing asked until the owner came to ask
why.  Only `plan.add` appends a line to a plan, and each of its callers says here how the seat
hears of the line, each way held by its own tests and alike on every harness: the seat wrote
it itself; a run's ending names it and is typed into the seat; or it goes only to a seat at
work, whose turn's end sends it to its open line.  A new writer fails here until it says how
its seat hears of the line, and one that is gone fails until its entry goes too.
"""

import ast
from pathlib import Path
import tempfile
import unittest

REPO = Path(__file__).resolve().parent.parent

WRITERS = {
    ("plan", "main"): "the seat's own `ak plan add`",
    ("handback", "plan_followup"): "a review follow-up: named by the run ending typed into "
                                   "the seat, or held by a fix run until that run's own ending "
                                   "is (test_followup_lines, test_followup_runs)",
    ("retire", "hand"): "a proven switch: only to a seat at work or one whose plan names it "
                        "(test_switch_retirement)",
}


def plan_writers(path):
    """The (module, function) pairs of that module that call `plan.add`, by any name it was
    imported under."""
    tree = ast.parse(path.read_text(), str(path))
    modules, functions = set(), {"add"} if path.stem == "plan" else set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name == "plan" and node.module in (None, "agentkit"):
                modules.add(alias.asname or alias.name)
            elif alias.name == "add" and node.module in ("plan", "agentkit.plan"):
                functions.add(alias.asname or alias.name)
    found = set()

    def visit(node, where):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call):
                func = child.func
                if ((isinstance(func, ast.Attribute) and func.attr == "add"
                     and isinstance(func.value, ast.Name) and func.value.id in modules)
                        or (isinstance(func, ast.Name) and func.id in functions)):
                    found.add((path.stem, where))
            defines = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            visit(child, child.name if defines else where)

    visit(tree, None)
    return found


class PlanLinesReachTheirSeat(unittest.TestCase):
    def test_every_writer_of_a_plan_line_says_how_its_seat_hears_of_it(self):
        found = set().union(*(plan_writers(path)
                              for path in sorted((REPO / "agentkit").glob("*.py"))))
        self.assertEqual(sorted(found - set(WRITERS)), [],
                         "a new writer of plan lines: say how its seat hears of the line")
        self.assertEqual(sorted(set(WRITERS) - found), [], "a writer that is gone")

    def test_a_call_under_any_import_name_is_found(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        source = Path(folder.name) / "acme_writer.py"
        source.write_text("from . import plan as notes\nfrom .plan import add as put\n\n\n"
                          "def one():\n    notes.add('acme-api', 'x', 'false')\n\n\n"
                          "def two():\n    def inner():\n        put('acme-api', 'x', 'false')\n"
                          "    return inner\n\n\nseen = set()\nseen.add(1)\n")
        self.assertEqual(plan_writers(source), {("acme_writer", "one"), ("acme_writer", "inner")})


if __name__ == "__main__":
    unittest.main()
