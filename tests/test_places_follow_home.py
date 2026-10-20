"""Each of ak's places follows HOME: a test that moves HOME alone has all of ak's state with it.

Run straight, as a seat or an `ak plan` check runs a file, a test starts at the owner's
~/.agentkit.  One that moved config.HOME but not config.STATE read the shipped config's usage and
wrote it over the owner's, every subscription's reading gone.
"""

import importlib
from pathlib import Path
import pkgutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agentkit
from agentkit import config


class PlacesFollowHome(unittest.TestCase):
    def test_moving_home_moves_every_place_and_the_files_named_in_them(self):
        with tempfile.TemporaryDirectory() as home, patch.object(config, "HOME", Path(home)):
            for name in config.PLACES:
                self.assertEqual(getattr(config, name).parent, Path(home), name)
            self.assertEqual(config.session_path("atoll").parent, Path(home) / "state")

    def test_a_place_moved_itself_stays_put_until_its_patch_ends(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as state, \
                patch.object(config, "HOME", Path(home)):
            with patch.object(config, "STATE", Path(state)):
                self.assertEqual(config.session_path("atoll"), Path(state) / "session-atoll.json")
            self.assertEqual(config.STATE, Path(home) / "state")

    def test_no_module_keeps_a_path_under_the_home_it_was_loaded_with(self):
        # A path built from a place when its module loads stays at the owner's home after a
        # test moves HOME: browser's VNC password files once did.
        for found in pkgutil.iter_modules(agentkit.__path__):
            importlib.import_module(f"agentkit.{found.name}")
        loaded = config.HOME
        with tempfile.TemporaryDirectory() as home, patch.object(config, "HOME", Path(home)):
            kept = [f"{name}.{key}" for name, module in sys.modules.items()
                    if name.startswith("agentkit.")
                    for key in dir(module)
                    if isinstance(value := getattr(module, key), Path)
                    and loaded in (value, *value.parents)
                    and config.REPO not in (value, *value.parents)]   # the code, not its state
        self.assertEqual(kept, [])


if __name__ == "__main__":
    unittest.main()
