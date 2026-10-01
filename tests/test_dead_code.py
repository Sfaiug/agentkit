"""Every top-level name has a whole-word mention outside its definitions in the product.

Strings count too: entry tables, manifests and plugin hooks can name a caller.
Imports need a mention in their own file. Tests and docs cannot keep a name alive.
Offline, one read per tracked product file.
"""

import ast
from collections import defaultdict
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SCOPE = ("agentkit/", "bin/", "hooks/", "tools/", "adapters/", "install.sh", "*.toml",
         ":!tests/", ":!docs/", ":!*.md")


def dead_names():
    paths = subprocess.check_output(
        ["git", "-C", str(REPO), "ls-files", "-z", "--", *SCOPE], text=True)
    mentions, definitions = defaultdict(set), defaultdict(list)
    candidates = []
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for path in filter(None, paths.split("\0")):
        source = (REPO / path).read_text(encoding="utf-8", errors="replace")
        for line, text in enumerate(source.splitlines(), 1):
            for word in set(re.findall(r"\b\w+\b", text)):
                mentions[word].add((path, line))
        if not (path.startswith("agentkit/") and path.endswith(".py")):
            continue
        tree = ast.parse(source, filename=path)
        # Same-named definitions cannot keep each other alive, even through recursion.
        for node in ast.walk(tree):
            if isinstance(node, kinds):
                definitions[node.name].append((path, node.lineno, node.end_lineno))
        for node in tree.body:
            local = isinstance(node, (ast.Import, ast.ImportFrom))
            if isinstance(node, kinds):
                names = [(node.name, node.lineno)]
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [(item.id, item.lineno) for target in targets for item in ast.walk(target)
                         if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)]
            elif local:
                if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                    continue    # future directives bind no local name
                names = [(alias.asname or alias.name.split(".")[0], alias.lineno)
                         for alias in node.names
                         if alias.name != "*"]
            else:
                continue
            for name, line in names:
                candidates.append((path, line, name, local))
                if not isinstance(node, kinds):
                    definitions[name].append((path, node.lineno, node.end_lineno))
    for name, spans in definitions.items():
        mentions[name] = {(path, line) for path, line in mentions[name]
                          if not any(path == p and first <= line <= last
                                     for p, first, last in spans)}
    return [f"{path}:{line} {name}" for path, line, name, local in sorted(candidates)
            if not any(not local or p == path for p, _ in mentions[name])]


class DeadCode(unittest.TestCase):
    def test_every_name_has_another_mention(self):
        dead = dead_names()
        if dead:
            self.fail("names with no outside mention:\n" + "\n".join(dead))

    def scan(self, sources):
        with patch.object(subprocess, "check_output", return_value="\0".join(sources) + "\0"), \
                patch.object(Path, "read_text", autospec=True, side_effect=lambda path, **_kw:
                             sources[path.relative_to(REPO).as_posix()]) as read:
            dead = dead_names()
        self.assertCountEqual([call.args[0].relative_to(REPO).as_posix()
                               for call in read.call_args_list], sources)
        return dead

    def test_assignments_need_an_outside_mention(self):
        self.assertEqual(self.scan({"agentkit/acme.py": (
            "UNUSED = 'UNUSED'\n"
            "ANNOTATED: int = 2\n"
            "LEFT = RIGHT = 3\n"
            "FIRST, (SECOND, *REST) = (1, (2, 3))\n"
            "LIVE = 4\n"
            "print(LIVE)\n"
            "LIVE.attr = 5\n"
            "print('UNUSED_SUFFIX', 'ANNOTATED_SUFFIX')\n")}), [
                "agentkit/acme.py:1 UNUSED", "agentkit/acme.py:2 ANNOTATED",
                "agentkit/acme.py:3 LEFT", "agentkit/acme.py:3 RIGHT",
                "agentkit/acme.py:4 FIRST", "agentkit/acme.py:4 REST",
                "agentkit/acme.py:4 SECOND"])

    def test_imports_need_a_mention_in_their_own_file(self):
        self.assertEqual(self.scan({"agentkit/acme.py": (
            "from __future__ import annotations\n"
            "import io, shutil\n"
            "from contextlib import (\n"
            "    redirect_stdout,\n"
            ")\n"
            "import xml.etree as tree\n"
            "import urllib.request\n"
            "from os import environ as env\n"
            "from pathlib import Path as unused_alias\n"
            "print(tree, urllib, env)\n"),
            "tools/acme.py": "print(io, shutil, redirect_stdout, unused_alias)\n"}), [
                "agentkit/acme.py:2 io", "agentkit/acme.py:2 shutil",
                "agentkit/acme.py:4 redirect_stdout", "agentkit/acme.py:9 unused_alias"])

    def test_same_named_definitions_are_not_callers(self):
        self.assertEqual(self.scan({"agentkit/acme.py": (
            "def estimate():\n"
            "    return history.estimate()\n"
            "async def recursive():\n"
            "    return recursive()\n"
            "class Unused:\n"
            "    label = 'Unused'\n"
            "class Live:\n"
            "    def estimate(self):\n"
            "        return estimate()\n"
            "print(Live)\n"),
            "agentkit/history.py": "def estimate():\n    return 1\n"}), [
                "agentkit/acme.py:1 estimate", "agentkit/acme.py:3 recursive",
                "agentkit/acme.py:5 Unused", "agentkit/history.py:1 estimate"])

    def test_entry_tables_manifests_and_strings_keep_names_alive(self):
        self.assertEqual(self.scan({"agentkit/acme.py": (
            "import module\n"
            "from plugin import callback\n"
            "SETTING = 1\n"
            "HOOK = 2\n"
            "def main():\n"
            "    getattr(module, 'callback')()\n"),
            "bin/ak": "ENTRY = {'acme': ('acme', 'main')}\n",
            "adapters/acme.toml": "setting = 'SETTING'\n",
            "hooks/acme.sh": "echo HOOK\n"}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
