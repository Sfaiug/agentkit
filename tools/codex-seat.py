#!/usr/bin/env python3
"""Launch Codex with a seat receipt and this seat's rulebook, or capture its SessionStart metadata."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit.harness.codex import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
