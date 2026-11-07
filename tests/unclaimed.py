"""Each answer key no line of go/keys.txt claims whole, sorted by what Go does with it.

    python3 tests/unclaimed.py

Each such key file runs whole, as tests/test_go_keys.py runs a claim and against the program it
judges, with a hand-over record of its own (AK_HANDOVER), and is listed once:

- it passes, so its claim can be made or widened;
- it fails and its record names hand-overs: under each line of it, `<command>: <site>`, the line
  most keys left first;
- it fails with no record, so Go answered and the key judged it wrong: with the first test that
  failed.

A report run when asked, never a check (tests/test_go_keys.py says why): it exits 0 whatever it
finds.
"""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import sys

from suite_shares import claims
from test_go_keys import REPO, checkout, run

# Each run has a memory cap: three keys at once is what it allows (AGENTS.md).
AT_ONCE = 3
# unittest names each failed test so, its errors before its failures.  A key failing outside any
# test, at its import or skipping each, is told by the last line it said.
FAILED = re.compile(r"^(?:FAIL|ERROR): .*", re.MULTILINE)


def main():
    whole = {name for name, *parts in claims(REPO) if not parts}
    keys = sorted(path.stem for path in REPO.glob("tests/test_key_*.py") if path.stem not in whole)
    passes, handed, wrong = [], defaultdict(list), {}
    with checkout(build=bool(keys)) as (tree, program, built):
        if built and built.returncode:
            sys.exit(built.stderr)
        # In the tree, which a key's box shows wherever it shows the key.
        records = Path(tree, ".handovers")
        records.mkdir()

        def judged(name):
            record = records / name
            done, passed = run(tree, program, name, AK_HANDOVER=str(record))
            return name, done, passed, record.read_text().splitlines() if record.exists() else []

        with ThreadPoolExecutor(AT_ONCE) as pool:
            for name, done, passed, lines in pool.map(judged, keys):
                if passed:
                    passes.append(name)
                elif lines:
                    for line in dict.fromkeys(lines):
                        handed[line].append(name)
                else:
                    said = FAILED.search(done.stderr) or done.stderr.strip().splitlines()[-1:]
                    wrong[name] = (said or [f"exit {done.returncode}"])[0]
                # the report takes as long as its slowest keys: this says it is still going
                print(name, "passes" if passed else "hands over" if lines else "answers wrong",
                      file=sys.stderr, flush=True)
    print(f"Passes: {len(passes)}")
    print("".join(f"  {name}\n" for name in passes), end="")
    print(f"Hands over: {len({name for names in handed.values() for name in names})}")
    for line, names in sorted(handed.items(), key=lambda item: (-len(item[1]), item[0])):
        print(f"  {line}")
        print("".join(f"    {name}\n" for name in names), end="")
    print(f"Answers wrong: {len(wrong)}")
    print("".join(f"  {name}: {said}\n" for name, said in wrong.items()), end="")


if __name__ == "__main__":
    main()
