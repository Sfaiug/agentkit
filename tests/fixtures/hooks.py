"""Run real hooks without starting an unrelated detached prose reader in their test HOME."""

import os
from pathlib import Path
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]


def run(command, *, env=None, read_prose=False, **kwargs):
    if read_prose or Path(command[-1]).name != "orchestrator-stop.sh":
        return subprocess.run(command, env=env, **kwargs)
    environment = dict(os.environ if env is None else env)
    with tempfile.TemporaryDirectory(prefix=".ak-test-hook-", dir=REPO) as tmp:
        # Some hook tests already inject host readings and concurrent writes at startup.
        roots = [kwargs.get("cwd", os.getcwd()), *environment.get("PYTHONPATH", "").split(os.pathsep)]
        existing = next((Path(root) / "sitecustomize.py" for root in roots
                         if root and (Path(root) / "sitecustomize.py").is_file()), None)
        startup = f"import runpy; runpy.run_path({str(existing)!r})\n" if existing else ""
        (Path(tmp) / "sitecustomize.py").write_text(
            startup + "from agentkit import prose\nprose.start = lambda *_a, **_kw: None\n")
        environment["PYTHONPATH"] = os.pathsep.join(
            [tmp, str(REPO), environment.get("PYTHONPATH", "")])
        return subprocess.run(command, env=environment, **kwargs)
