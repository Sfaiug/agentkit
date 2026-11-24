"""A suite piece's command gets the functions its image exports as the image defines them: piece.sh
defines no function, which bash would export to the command in place of one of that name, as an
image whose sh is bash hands on."""

import re
import unittest
from pathlib import Path

PIECE = (Path(__file__).resolve().parents[1] / "tools/helper/piece.sh").read_text()


class AHelperPieceHandsItsCommandTheSuiteSFunctions(unittest.TestCase):
    def test_piece_sh_defines_no_function(self):
        self.assertEqual(re.findall(r"^\s*(?:function\s.*|[^\s#]+\s*\(\).*)$", PIECE, re.M), [])


if __name__ == "__main__":
    unittest.main()
