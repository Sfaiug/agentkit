"""The answer-key check refuses a key importing agentkit itself or through a module under tests/
an import loads, as Python's finders give it, and lets one pass whose imports never load it.
Offline: the check runs on temporary trees, each a tests/ folder holding one key.
"""

from pathlib import Path
import tempfile
import unittest

from test_keys_run_ak_from_outside import importers

AK = "from agentkit import gate\n"


class AKeyImportingAkThroughAHelperIsRefused(unittest.TestCase):
    def refused(self, key, **files):
        """Whether the check refuses `key` beside `files`, each named by its path under tests/
        with `__` for `/`."""
        with tempfile.TemporaryDirectory() as tmp:
            tests = Path(tmp, "tests")
            for name, text in {"test_key_acme": key, **files}.items():
                (tests / f"{name.replace('__', '/')}.py").parent.mkdir(parents=True, exist_ok=True)
                (tests / f"{name.replace('__', '/')}.py").write_text(text)
            return importers(tests) == {"test_key_acme"}

    def test_a_key_importing_agentkit_itself_is_refused(self):
        self.assertTrue(self.refused(AK))

    def test_a_helper_importing_agentkit_is_refused(self):
        self.assertTrue(self.refused("from fixtures import acme\n", fixtures__acme=AK))

    def test_a_helper_importing_agentkit_relatively_through_another_is_refused(self):
        self.assertTrue(self.refused("from fixtures import acme\n",
                                     fixtures__acme="from .base import x\n", fixtures__base=AK))

    def test_a_module_under_tests_shadowing_the_standard_library_is_refused(self):
        self.assertTrue(self.refused("import json\n", json=AK))

    def test_a_name_a_helper_defines_loads_no_module_beside_it(self):
        self.assertFalse(self.refused("from fixtures.acme import value\n",
                                      fixtures__acme="value = 1\n", fixtures__acme__value=AK))

    def test_a_builtin_module_comes_before_one_under_tests(self):
        self.assertFalse(self.refused("import sys\n", sys=AK))


if __name__ == "__main__":
    unittest.main()
