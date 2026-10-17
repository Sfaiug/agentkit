#!/usr/bin/env python3
"""The static model table of one harness, the way its adapter's `models` verb prints it.

Usage: catalog.py <harness> [model ...]

One `id<TAB>label<TAB>efforts` line per model of the `[catalog]` table in adapters/<harness>.toml,
the efforts space-separated and strongest last: `none` for a model that runs at no effort, and
empty where the table does not say.  Given models -- each an id, or a listing's own
`id<TAB>label<TAB>efforts` line -- one line for each of those instead: the table's where it has
that id, else the listing's own, else the id alone, its efforts unsaid.  That is how a harness
that lists only its ids gets their efforts, and how the table corrects one that lists its own.
The table is the whole answer for a harness that cannot list its own models, and the fallback
for one whose listing failed.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config

known = {model["id"]: model for model in config.catalog_table(sys.argv[1])}
for name in sys.argv[2:] or list(known):
    model, label, efforts = (name.split("\t") + ["", ""])[:3]
    model = known.get(model) or {"id": model, "label": label or model, "efforts": efforts.split()}
    print(model["id"], model["label"], " ".join(model["efforts"]), sep="\t")
