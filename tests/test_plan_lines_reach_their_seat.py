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


def plan_writers(root):
    """The (module, function) pairs under `root`/agentkit that call `plan.add`, however it was
    imported: each call's dotted name is resolved through its module's imports, and a name
    imported from nowhere is the module's own."""
    found = set()
    for path in sorted((root / "agentkit").rglob("*.py")):
        parts = path.relative_to(root).with_suffix("").parts
        package = parts[:-1]
        module = ".".join(package if parts[-1] == "__init__" else parts)
        names = {}
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                base = ".".join(package[:len(package) - node.level + 1] if node.level else ())
                source = ".".join(filter(None, (base, node.module)))
                for alias in node.names:
                    names[alias.asname or alias.name] = f"{source}.{alias.name}"

        def dotted(node):
            if isinstance(node, ast.Name):
                return names.get(node.id, f"{module}.{node.id}")
            if isinstance(node, ast.Attribute):
                return f"{dotted(node.value)}.{node.attr}"
            return ""

        def visit(node, where):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Call) and dotted(child.func) == "agentkit.plan.add":
                    found.add((module.removeprefix("agentkit."), where))
                defines = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                visit(child, child.name if defines else where)

        visit(tree, None)
    return found


class PlanLinesReachTheirSeat(unittest.TestCase):
    def test_every_writer_of_a_plan_line_says_how_its_seat_hears_of_it(self):
        found = plan_writers(REPO)
        self.assertEqual(sorted(found - set(WRITERS)), [],
                         "a new writer of plan lines: say how its seat hears of the line")
        self.assertEqual(sorted(set(WRITERS) - found), [], "a writer that is gone")

    def test_a_call_under_any_import_name_is_found(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        (root / "agentkit" / "harness").mkdir(parents=True)
        (root / "agentkit" / "acme_writer.py").write_text(
            "from . import plan as notes\nfrom .plan import add as put\n"
            "import agentkit.plan as jot\nimport agentkit.plan\n\n\n"
            "def one():\n    notes.add('acme-api', 'x', 'false')\n\n\n"
            "def two():\n    def inner():\n        put('acme-api', 'x', 'false')\n"
            "    return inner\n\n\n"
            "def three():\n    jot.add('acme-api', 'x', 'false')\n\n\n"
            "def four():\n    agentkit.plan.add('acme-api', 'x', 'false')\n\n\n"
            "seen = set()\nseen.add(1)\n")
        (root / "agentkit" / "harness" / "acme.py").write_text(
            "from .. import plan\n\n\ndef five():\n    plan.add('acme-api', 'x', 'false')\n")
        self.assertEqual(plan_writers(root), {
            ("acme_writer", "one"), ("acme_writer", "inner"), ("acme_writer", "three"),
            ("acme_writer", "four"), ("harness.acme", "five")})


if __name__ == "__main__":
    unittest.main()
