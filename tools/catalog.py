#!/usr/bin/env python3
"""The static model table of one harness, the way its adapter's `models` verb prints it.

Usage: catalog.py <harness> [model ...]

One `id<TAB>label<TAB>efforts` line per model of the `[catalog]` table in adapters/<harness>.toml,
the efforts space-separated and strongest last: `none` for a model that runs at no effort, and
empty where the table does not say.  Given models, one line for each of those instead -- the
table's where it has one, else the id alone, its efforts unsaid -- which is how a harness that
lists only its ids gets their efforts.  The table is the whole answer for a harness that cannot
list its own models, and the fallback for one whose listing failed.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config

known = {model["id"]: model for model in config.catalog_table(sys.argv[1])}
for name in sys.argv[2:] or list(known):
    model = known.get(name) or {"id": name, "label": name, "efforts": []}
    print(model["id"], model["label"], " ".join(model["efforts"]), sep="\t")
