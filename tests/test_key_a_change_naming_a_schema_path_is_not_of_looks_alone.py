"""A change naming a schema path is not of looks alone.

A change that names, against its target, a path with a part `migrations` or `alembic`, or the
suffix `.sql` in any case, is never of looks alone
(tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py), whatever kind of file the
path is, an image or a timed test it edits among them: ak reverts no release naming one, so
it lands through the whole suite.  The same image elsewhere is of looks alone.

On that key's fixtures, a line on a target declaring `health:` and `deployed:` with a time record
of its suite, `looks_alone.changes` is asked, in its Home, of a branch for each change.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REPO
import test_key_a_change_of_looks_alone_lands_on_its_quick_checks as quick

PNG = quick.IMAGE["logo.png"]
TEST = "migrations/tests/look_test.sh"
ASK = ("import json, sys; sys.path.insert(0, sys.argv[1]); from agentkit import looks_alone; "
       "print(json.dumps(looks_alone.changes(sys.argv[2], 'main', sys.argv[3:])))")


class AChangeNamingASchemaPathIsNotOfLooksAlone(unittest.TestCase):
    line = vars(quick.AChangeOfLooksAloneLandsOnItsQuickChecks)["line"]

    def test_only_the_image_off_any_schema_path_is_of_looks_alone(self):
        line = self.line(times={TEST: 1}, **{TEST: "true\n"})
        changes = {"elsewhere": {"site/logo.png": PNG},
                   "migrations": {"migrations/logo.png": PNG},
                   "alembic": {"db/alembic/logo.png": PNG},
                   "sql": {**quick.IMAGE, "db/SCHEMA.SQL": "x\n"},
                   "test": {**quick.IMAGE, TEST: "true  # blink\n"}}
        heads = {line.rig.branch(f"ak/{name}", files): name for name, files in changes.items()}
        done = line.home.run(sys.executable, "-c", ASK, str(REPO), str(line.rig.path), *heads)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual({heads[head]: tests for head, tests in json.loads(done.out).items()},
                         {"elsewhere": []})


if __name__ == "__main__":
    unittest.main()
