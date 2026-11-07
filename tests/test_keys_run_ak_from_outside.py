"""An answer key runs the program `AK_BIN` names from outside.  One that imports Python ak's own
package, `agentkit`, answers for Python alone: `tests/test_go_keys.py` runs every key Go claims
with agentkit/ taken out, so Go could never claim it.  A key fails here where an import statement,
wherever it stands, imports agentkit in its own file or in a module under tests/ that one of its
import statements loads, directly or through further such modules.  A key reaching the package
another way, through importlib, `__import__`, exec, a child python3 or a folder it puts on its own
sys.path, is left to that copy without agentkit/, once Go claims the key.
Offline: the files of this checkout.
"""

import ast
from importlib.machinery import BuiltinImporter, FrozenImporter, ModuleSpec, PathFinder
from importlib.util import module_from_spec, resolve_name
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
# The keys that imported agentkit when this check came (7 Nov 2026): the set only shrinks.
BEFORE = {"test_key_no_line_is_typed_into_a_composer_ak_cannot_read_whole",
          "test_key_red_tests_rerun_at_once", "test_key_seat_runs_the_live_ak"}


def importers(tests):
    """The keys in the folder `tests` that import agentkit, themselves or through the modules
    under `tests` their imports load.  A module is the one Python's own finders give, searched as
    a key's process searches: `tests` first, then the rest of this process's sys.path, as this
    runs from tests/ too.  Finding runs no module's code, and a folder under tests/ holds no
    __init__.py, so a package there is a namespace package: it holds nothing but its modules
    and the names Python gives every namespace package."""
    path, specs, statements = [str(tests), *sys.path[1:]], {}, {}
    namespace = module_from_spec(ModuleSpec("namespace", None, is_package=True))

    def spec(name):
        if name not in specs:
            parent = name.rpartition(".")[0]
            # A submodule is searched for in its package alone, and a plain module holds none.
            where = (spec(parent).submodule_search_locations or []) if parent else path
            # PathFinder's own search, not its find_spec: that gives a namespace package inside
            # another a __path__ read from its parent in sys.modules, which only an import fills.
            # What it finds nowhere comes back as a namespace package of no folder.
            specs[name] = (BuiltinImporter.find_spec(name) or FrozenImporter.find_spec(name)
                           or PathFinder._get_spec(name, where))
        return specs[name]

    def imports(file):
        """Each import statement in `file`: the dots before its module's name, that name, and
        the names a `from` takes from it, none for a plain import of each of its names."""
        if file not in statements:
            # Bytes, so the parser decodes them as Python running them does: a BOM, a coding line.
            nodes = ast.walk(ast.parse(Path(file).read_bytes()))
            statements[file] = [found for node in nodes for found in (
                [(0, alias.name, ()) for alias in node.names] if isinstance(node, ast.Import)
                else [(node.level, node.module or "", [alias.name for alias in node.names])]
                if isinstance(node, ast.ImportFrom) else [])]
        return statements[file]

    def reaches(key):
        seen, todo = set(), [("__main__", str(key))]
        while todo:
            name, file = todo.pop()
            for level, module, names in imports(file):
                try:
                    module = resolve_name("." * level + module, name.rpartition(".")[0])
                except ImportError:
                    # Relative to no package, or beyond the top one: it loads nothing.
                    continue
                parts = module.split(".")
                if parts[0] == "agentkit":
                    return True
                # A from-list loads a package's module only for a name the package lacks, and a
                # star only the names in its __all__, which no namespace package has.
                for loaded in [*(".".join(parts[:end]) for end in range(1, len(parts) + 1)),
                               *(f"{module}.{taken}" for taken in names
                                 if taken != "*" and not hasattr(namespace, taken))]:
                    found = spec(loaded)
                    if (loaded not in seen and found.has_location
                            and Path(found.origin).is_relative_to(tests)):
                        seen.add(loaded)
                        todo.append((loaded, found.origin))
        return False

    return {key.stem for key in tests.glob("test_key_*.py") if reaches(key)}


class KeysRunAkFromOutside(unittest.TestCase):
    def test_no_key_imports_python_aks_own_package(self):
        keys = importers(REPO / "tests")
        self.assertEqual(keys - BEFORE, set(), "an answer key runs ak from outside, as "
                         "tests/fixtures/akbin.py does, never Python ak's own modules")
        self.assertEqual(BEFORE - keys, set(), "a key that runs ak from outside leaves BEFORE")

    def test_no_folder_under_tests_runs_code_on_import(self):
        self.assertEqual(list((REPO / "tests").rglob("__init__.py")), [], "an __init__.py "
                         "decides what importing its folder loads, which importers() does not read")


if __name__ == "__main__":
    unittest.main()
