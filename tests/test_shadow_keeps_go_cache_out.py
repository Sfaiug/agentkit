"""tests/shadow.py keeps Go's compiled SQLite out: a fake Go, Python's ak, that then writes a file
under $HOME/.cache/agentkit/sqlite, where go/internal/sqlite keeps it, is named for nothing; one
that writes beside it, under $HOME/.cache/agentkit/other, is named for a difference in HOME; the
Home keeps every byte and modification time.  Where a part of that path is a link to a folder, or
a file, the box is built still, every run starts, and each sees every path the home holds."""

from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from test_shadow import GO, Shadowing, every_byte_and_time

CACHE = Path(".cache/agentkit/sqlite")
# What the box mounts nothing over: a part of CACHE that is a link to a folder of the home, CACHE
# then leading to `cached/agentkit/sqlite`, `.cache/sqlite` or `.cache`, or a file (None).
IN_THE_WAY = ((".cache", "cached"), (".cache/agentkit", "."), (".cache/agentkit/sqlite", ".."),
              (".cache", None), (".cache/agentkit/sqlite", None))


class KeepsGoCacheOut(Shadowing):
    @unittest.skipUnless(boxable(), "no bwrap able to build a box here")
    def test_only_the_compiled_sqlite_is_kept_out(self):
        (self.home.path / ".cache").mkdir()     # as most homes have it
        before = every_byte_and_time(self.home.path)
        for folder, outcome in (("sqlite", (0, set())), ("other", (1, {"home"}))):
            with self.subTest(folder):
                more = (f'mkdir -p "$HOME/.cache/agentkit/{folder}" && '
                        f'echo compiled >"$HOME/.cache/agentkit/{folder}/sqlite3.wasm"')
                code, named, said = self.shadow("--go", self.fake(folder, GO.format(more)))
                self.assertEqual((code, named), outcome, said)
        self.assertEqual(every_byte_and_time(self.home.path), before)

    @unittest.skipUnless(boxable(), "no bwrap able to build a box here")
    def test_a_link_or_a_file_on_its_path_hides_nothing(self):
        # Go's place lists HOME in its box, links not followed; Python's, as it is outside any.
        seen, listing = self.fake("seen", 'find "$HOME"'), self.fakes / "listing"
        outside = self.fake("outside", f"cat {shlex.quote(str(listing))}")
        for path, link in IN_THE_WAY:
            with self.subTest(path, link=link):
                for name in (".cache", "cached"):
                    gone = self.home.path / name
                    if gone.is_dir() and not gone.is_symlink():
                        shutil.rmtree(gone)
                    gone.unlink(missing_ok=True)
                made = self.home.path / path
                if link:
                    (made.parent / link).mkdir(parents=True, exist_ok=True)
                    made.symlink_to(link)
                    # a file where the cache's path leads, which a tmpfs there would hide
                    (self.home.path / CACHE).mkdir(parents=True, exist_ok=True)
                    (self.home.path / CACHE / "kept").write_text("acme")
                else:
                    made.parent.mkdir(parents=True, exist_ok=True)
                    made.write_text("acme")
                listing.write_text(self.home.run(seen).out)
                code, named, said = self.shadow("--python", outside, "--go", seen)
                self.assertEqual((code, named), (0, set()), said)


if __name__ == "__main__":
    unittest.main(verbosity=2)
