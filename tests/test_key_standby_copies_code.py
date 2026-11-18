"""`ak standby ALIAS` copies ~/code whole, a project's `.git` folder and what git ignores too; the
next pass brings what changed and takes what the home removed.  A file beside ~/code does not
come, and a home without ~/code leaves the copy's as it was.  Black-box (fixtures/twohomes.py)."""

from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

MAIN, GIT, IGNORED = "code/acme-api/main.py", "code/acme-api/.git/HEAD", "code/acme-api/.venv/cfg"
OTHER, BESIDE = "code/acme-web/index.html", "notes/plan.txt"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassCopiesTheProjects(unittest.TestCase):
    def test_a_pass_copies_code_whole_then_what_changed_and_what_the_home_removed(self):
        with Machines("acme-mini", "acme-vm") as (home, here):
            here.client_of(home)
            for path in (MAIN, GIT, IGNORED, OTHER, BESIDE):
                home.write(path, f"the home's {path}")
            def code(machine):
                return {at: data for at, data in machine.tree().items() if at.startswith("code/")}
            for change in (lambda: None,
                           lambda: (home.write(MAIN, "changed"), (home.path / IGNORED).unlink(),
                                    shutil.rmtree(home.path / "code/acme-web"))):
                change()
                done = here.ak("standby", home.name)
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(code(here), code(home))
            self.assertEqual({MAIN, GIT} & set(code(here)), {MAIN, GIT})
            self.assertNotIn(BESIDE, here.tree())
            shutil.rmtree(home.path / "code")
            done = here.ak("standby", home.name)
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertIn(GIT, code(here))


if __name__ == "__main__":
    unittest.main()
