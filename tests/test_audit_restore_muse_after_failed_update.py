"""Finding 13: destructive fake installers and offline stand-ins for both live gates."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time
from unittest.mock import MagicMock

import pytest

from test_audit_enforce_harness_update_pins import pinned_home, muse, REPO
from agentkit import config, retention, update

OLD = "1.1.1-R2514.1"
NEW = "1.1.1-R2514.2"  # Same semantic release: the build identity must still change.

LAUNCHER = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
here = pathlib.Path(__file__).resolve().parent
record = pathlib.Path(os.environ["PIN_RECORD"])
pin = os.environ.get("MUSE_NO_AUTO_UPDATE")
install = os.environ.get("MUSE_LAUNCHER_INSTALL")
with record.open("a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "pin": pin, "install": install}) + "\\n")
if install == "1" or pin != "1":
    record.with_suffix(".updated").write_text("mutated")
    old = (here / ".muse-version").read_text().strip()
    new = old if os.environ.get("SAME_BUILD") == "1" else "1.1.1-R2514.2"
    data = (here / ("muse-bin-" + old)).read_bytes()
    (here / ("muse-bin-" + old)).unlink()
    target = here / ("muse-bin-" + new)
    target.write_bytes(data.replace(b"1.1.1-R2514.1", new.encode()) + b"\\n# replaced binary\\n")
    target.chmod(0o755)
    (here / ".muse-version").write_text(new + "\\n")
    (here / ".muse-version").chmod(0o600)
    (here / ".muse-release-info.json").write_text(json.dumps({"version": new, "changed": True}))
    (here / ".muse-update-checked-at").write_text("9999999")
    (here / ".muse-update-notice").write_text(old + "\\t" + new)
    if (here / "muse-bin").is_symlink():
        (here / "muse-bin").unlink()
    launcher = pathlib.Path(__file__).resolve()
    launcher.write_bytes(launcher.read_bytes() + b"\\n# replaced launcher\\n")
    launcher.chmod(0o700)
    entry = pathlib.Path(os.environ["MUSE_ENTRY"])
    if entry.is_symlink():
        entry.unlink()
        entry.symlink_to(launcher)
    if os.environ.get("BROKEN_BUILD") == "1":
        target.unlink()
    time.sleep(float(os.environ.get("UPGRADE_SLEEP", "0")))
    sys.exit(int(os.environ.get("UPGRADE_EXIT", "0")))
build = (here / ".muse-version").read_text().strip()
sys.exit(subprocess.run([str(here / ("muse-bin-" + build)), *sys.argv[1:]]).returncode)
'''


@pytest.fixture
def layout(pinned_home, monkeypatch):
    root = pinned_home
    install = root / "install with spaces"
    install.mkdir(mode=0o750)
    launcher = install / "muse-launcher"
    launcher.write_text(LAUNCHER)
    launcher.chmod(0o751)
    entry = root / "bin/muse"
    entry.unlink()
    entry.symlink_to("../install with spaces/launch-link")
    (install / "launch-link").symlink_to("muse-launcher")
    binary = install / f"muse-bin-{OLD}"
    binary.write_text('''#!/usr/bin/env python3
import os, sys
assert os.environ.get("MUSE_NO_AUTO_UPDATE") == "1"
assert os.environ.get("MUSE_LAUNCHER_INSTALL") == "0"
print("Muse Code 1.1.1")
print("build 1.1.1-R2514.1 (commit abcdef)")
''')
    binary.chmod(0o711)
    (install / "muse-bin").symlink_to(binary.name)
    (install / ".muse-version").write_text(OLD + "\n")
    (install / ".muse-version").chmod(0o640)
    (install / ".muse-release-info.json").write_text(json.dumps({"version": OLD, "manifest_url": "offline"}))
    (install / ".muse-release-info.json").chmod(0o600)
    (install / ".muse-update-checked-at").write_text("123456\n")
    monkeypatch.setenv("MUSE_ENTRY", str(entry))
    monkeypatch.setenv("UPGRADE_EXIT", "0")
    monkeypatch.setenv("SAME_BUILD", "0")
    monkeypatch.setenv("BROKEN_BUILD", "0")
    # Fake versioned installs for the other harnesses let the test check that preflight
    # happens before *any* harness mutation and that partial upgrades revert together.
    for name in ("claude", "codex"):
        (root / f"{name}.version").write_text("1.0.0")
        script = root / "bin" / name
        script.write_text(f'''#!/bin/sh
if [ "$1" = --version ]; then cat "$HOME/{name}.version"; exit; fi
[ "$1" = install ] || exit 2
v=$2; [ "$v" != latest ] || v=2.0.0
printf '%s' "$v" >"$HOME/{name}.version"
''')
        script.chmod(0o755)
    npm = root / "bin/npm"
    npm.write_text('''#!/bin/sh
v=${3##*@}; [ "$v" != latest ] || v=2.0.0
printf '%s' "$v" >"$HOME/codex.version"
''')
    npm.chmod(0o755)
    monkeypatch.setattr(update, "fresh_unavailable", lambda: "")
    gates = []
    real_step = update.step
    def step(cmd, fh, env=None, timeout=update.STEP_CAP):
        if cmd[0] == "bash":
            assert cmd == ["bash", str(REPO / "tests/smoke.sh")]
            assert env["AGENTKIT_ACCEPTANCE_REQUIRED"] == "1"
            gates.append("smoke")
            return os.environ.get("SMOKE_EXIT", "0") == "0"
        return real_step(cmd, fh, env, timeout)
    def fresh_gate(fh, log):
        gates.append("fresh")
        return os.environ.get("FRESH_EXIT", "0") == "0", "offline fixture"
    monkeypatch.setattr(update, "step", step)
    monkeypatch.setattr(update, "fresh_gate", fresh_gate)
    monkeypatch.setenv("SMOKE_EXIT", "0")
    monkeypatch.setenv("FRESH_EXIT", "0")
    return root, install, gates


def contents(paths):
    return {str(p): (os.readlink(p) if p.is_symlink() else p.read_bytes(),
                     stat.S_IMODE(p.lstat().st_mode), p.is_symlink()) for p in paths}


def invoke():
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        rc = update.main([])
    return rc, output.getvalue()


@pytest.mark.parametrize("failure", ["upgrade", "smoke", "fresh", "same-build", "broken-build"])
def test_failed_updates_restore_exact_launcher_build_metadata_links_and_modes(layout, monkeypatch, failure):
    root, install, gates = layout
    paths = [root / "bin/muse", *install.iterdir()]
    before = contents(paths)
    identity = update.version(muse())
    if failure in ("upgrade", "same-build"):
        monkeypatch.setenv("UPGRADE_EXIT", "9")
    if failure == "same-build":
        monkeypatch.setenv("SAME_BUILD", "1")
    if failure == "broken-build":
        monkeypatch.setenv("BROKEN_BUILD", "1")
    if failure in ("smoke", "fresh"):
        monkeypatch.setenv(f"{failure.upper()}_EXIT", "1")
    rc, output = invoke()
    assert rc == 1, output
    assert "muse: reverted, back on " + identity in output
    assert contents(paths) == before
    assert set(install.iterdir()) == set(paths[1:])
    assert update.version(muse()) == identity
    assert (root / "claude.version").read_text() == "1.0.0"
    assert (root / "codex.version").read_text() == "1.0.0"
    expected = {"upgrade": [], "same-build": [], "broken-build": [],
                "smoke": ["smoke"], "fresh": ["smoke", "fresh"]}
    assert gates == expected[failure]
    records = [json.loads(line) for line in (root / "launches.jsonl").read_text().splitlines()]
    assert all(r["pin"] == "1" and r["install"] == "0" for r in records if r["argv"] == ["--version"])
    assert any(r["install"] == "1" for r in records)
    assert not list(config.TMP.glob("muse-snapshot-*"))


def test_snapshot_manifest_contains_complete_restorable_bytes_links_and_modes(layout):
    root, install, _ = layout
    before = contents([root / "bin/muse", *install.iterdir()])
    identity = update.version(muse())
    with update.MuseSnapshot(muse(), identity) as snapshot:
        manifest = json.loads((snapshot.path / "manifest.json").read_text())
        assert manifest["identity"] == identity
        assert {e["path"] for e in manifest["files"]} == set(before)
        for entry in manifest["files"]:
            backup = snapshot.path / entry["saved"]
            assert contents([backup])[str(backup)] == before[entry["path"]]
        snapshot.restore()
        assert not snapshot.path.exists()


def test_success_keeps_new_build_only_after_both_gates(layout):
    root, install, gates = layout
    rc, output = invoke()
    assert rc == 0, output
    assert gates == ["smoke", "fresh"]
    assert OLD in output and NEW in output
    assert "muse: upgraded" in output
    assert (install / ".muse-version").read_text().strip() == NEW
    assert not (install / f"muse-bin-{OLD}").exists()
    assert NEW in update.version(muse())
    assert not list(install.glob(".ak-muse-restore-*"))
    assert not list(config.TMP.glob("muse-snapshot-*"))


@pytest.mark.parametrize("unsafe", ["metadata-missing", "metadata-mismatch", "binary-missing",
                                   "not-executable", "directory", "external-link", "cyclic-link",
                                   "hardlink", "read-only-parent", "installer-lock", "copy-failure"])
def test_preflight_stops_before_any_harness_mutation(layout, monkeypatch, unsafe):
    root, install, gates = layout
    binary = install / f"muse-bin-{OLD}"
    if unsafe == "metadata-missing":
        (install / ".muse-release-info.json").unlink()
    elif unsafe == "metadata-mismatch":
        (install / ".muse-release-info.json").write_text('{"version":"different"}')
    elif unsafe == "binary-missing":
        binary.unlink()
    elif unsafe == "not-executable":
        binary.chmod(0o600)
    elif unsafe == "directory":
        (install / "muse-bin-extra").mkdir()
    elif unsafe == "external-link":
        (install / "muse-bin-extra").symlink_to(root / "claude.version")
    elif unsafe == "cyclic-link":
        (install / "muse-bin-extra").symlink_to("muse-bin-extra")
    elif unsafe == "hardlink":
        os.link(binary, root / "shared-binary")
    elif unsafe == "read-only-parent":
        install.chmod(0o550)
    elif unsafe == "installer-lock":
        (install / ".muse-update-lock").mkdir()
    elif unsafe == "copy-failure":
        monkeypatch.setattr(update.shutil, "copy2", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    try:
        rc, output = invoke()
    finally:
        install.chmod(0o750)
    assert rc == 1, output
    assert "nothing was upgraded; the gate was not run" in output
    assert not (root / "launches.updated").exists()
    assert (root / "claude.version").read_text() == "1.0.0"
    assert (root / "codex.version").read_text() == "1.0.0"
    assert gates == []


@pytest.mark.parametrize("unsafe", ["changed-parent", "bad-copy", "stage-link"])
def test_unsafe_restore_is_refused_before_replacing_any_file(layout, unsafe):
    root, install, _ = layout
    with update.MuseSnapshot(muse(), update.version(muse())) as snapshot:
        if unsafe == "changed-parent":
            install.chmod(0o700)
        elif unsafe == "bad-copy":
            next(p for p in snapshot.saved.values() if not p.is_symlink()).write_text("corrupt backup")
        elif unsafe == "stage-link":
            staged = snapshot.staged[install]
            moved = staged.with_name("displaced-stage")
            staged.rename(moved)
            staged.symlink_to(moved, target_is_directory=True)
        launcher = (install / "muse-launcher").read_bytes()
        with pytest.raises((OSError, config.Error)):
            snapshot.restore()
        assert (install / "muse-launcher").read_bytes() == launcher
    assert snapshot.path.exists()


def test_failed_restore_is_reported_and_backup_is_retained(layout, monkeypatch):
    root, install, _ = layout
    monkeypatch.setenv("UPGRADE_EXIT", "1")
    monkeypatch.setattr(update.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("restore denied")))
    rc, output = invoke()
    assert rc == 1
    assert "muse: cannot revert, restore denied; snapshot retained at " in output
    snapshots = list(config.TMP.glob("muse-snapshot-*"))
    assert len(snapshots) == 1
    assert (snapshots[0] / "manifest.json").exists()
    assert not retention.marker(snapshots[0]).exists()


def test_restore_must_pass_the_pinned_version_command(layout, monkeypatch):
    root, install, gates = layout
    binary = install / f"muse-bin-{OLD}"
    with binary.open("a") as fh:
        fh.write('sys.exit(17 if os.environ.get("FAIL_VERSION") == "1" else 0)\n')
    before = contents([binary, install / "muse-launcher"])
    def fail_gate(fh, log):
        monkeypatch.setenv("FAIL_VERSION", "1")
        return False, "offline gate failed"
    monkeypatch.setattr(update, "fresh_gate", fail_gate)
    rc, output = invoke()
    assert rc == 1
    assert "muse: cannot revert, restored Muse failed its pinned version check" in output
    assert contents([binary, install / "muse-launcher"]) == before
    assert list(config.TMP.glob("muse-snapshot-*/manifest.json"))
    assert update.version(muse()) == ""


def test_concurrent_updates_cannot_snapshot_the_same_install(layout):
    root, install, gates = layout
    identity = update.version(muse())
    with update.MuseSnapshot(muse(), identity):
        rc, output = invoke()
        assert rc == 1
        assert "nothing was upgraded; the gate was not run" in output
        assert not (root / "launches.updated").exists()
        assert gates == []


def test_build_marker_completes_a_short_version_output(layout):
    root, install, _ = layout
    binary = install / f"muse-bin-{OLD}"
    binary.write_text('#!/bin/sh\nprintf "Muse Code 1.1.1\\n"\n')
    assert update.version(muse()) == f"Muse Code 1.1.1 (installed build {OLD})"


def test_versioned_reverts_use_release_tokens_but_verify_full_identity(layout, monkeypatch):
    root, install, _ = layout
    before = {"claude": "Claude Code 1.0.0 (build abc)", "codex": "codex-cli 1.0.0", "muse": ""}
    after = {"claude": "Claude Code 2.0.0 (build def)", "codex": "codex-cli 2.0.0", "muse": ""}
    commands = []
    monkeypatch.setattr(update, "version", lambda h: before[h["name"]])
    monkeypatch.setattr(update, "step", lambda cmd, *a: commands.append(cmd) or True)
    # the plan main hands revert: only the harnesses this host has
    plan = [h for h in update.harnesses() if h["name"] in before]
    landed = update.revert(plan, before, after, None, lambda message: None)
    assert commands == [["claude", "install", "1.0.0"], ["npm", "i", "-g", "@openai/codex@1.0.0"]]
    assert landed["claude"] == ("reverted", "back on Claude Code 1.0.0 (build abc)")
    assert landed["codex"] == ("reverted", "back on codex-cli 1.0.0")


def test_accepted_update_reports_snapshot_cleanup_errors(layout, monkeypatch):
    root, install, gates = layout
    real_rmtree = update.shutil.rmtree
    def cannot_remove_snapshot(path, *a, **kw):
        if Path(path).name.startswith("muse-snapshot-"):
            raise OSError("cleanup denied")
        return real_rmtree(path, *a, **kw)
    monkeypatch.setattr(update.shutil, "rmtree", cannot_remove_snapshot)
    rc, output = invoke()
    assert rc == 0, output
    assert gates == ["smoke", "fresh"]
    assert "snapshot cleanup failed" in output
    assert NEW in update.version(muse())
    snapshots = list(config.TMP.glob("muse-snapshot-*"))
    assert len(snapshots) == 1
    receipt = retention.read_json(retention.marker(snapshots[0]))
    assert receipt["kind"] == "update" and receipt["finished_at"]


@pytest.mark.parametrize("lock_kind", ["dead", "live", "missing-pid", "invalid-pid"])
def test_installer_lock_staleness_and_actionable_errors(layout, lock_kind):
    root, install, gates = layout
    lock = install / ".muse-update-lock"
    lock.mkdir()
    if lock_kind == "dead":
        child = subprocess.Popen(["/bin/true"])
        child.wait()
        (lock / "pid").write_text(str(child.pid))
    elif lock_kind == "live":
        (lock / "pid").write_text(str(os.getpid()))
    elif lock_kind == "invalid-pid":
        (lock / "pid").write_text("not a pid")
    rc, output = invoke()
    assert str(lock) in output
    if lock_kind == "dead":
        assert rc == 0, output
        assert "removed stale Muse installer lock" in output
        assert not lock.exists()
        assert gates == ["smoke", "fresh"]
    else:
        assert rc == 1
        assert lock.is_dir()
        assert gates == []
        assert not (root / "launches.updated").exists()
        assert "running pid" in output if lock_kind == "live" else "inspect the lock" in output


def test_timeout_kills_forked_installer_and_reclaims_its_lock_before_restore(layout, monkeypatch):
    root, install, gates = layout
    launcher = install / "muse-launcher"
    # The same update_binary() subshell and $$ lock owner as the real Muse launcher.
    # The Python stand-in is a grandchild; if either descendant survives, it writes again
    # after the attempted rollback. This fixture deliberately leaves its lock on SIGKILL.
    driver = root / "installer-driver.py"
    code = LAUNCHER.split("\n", 1)[1].replace(
        'here = pathlib.Path(__file__).resolve().parent',
        '__file__ = os.environ["FIXTURE_LAUNCHER"]\nhere = pathlib.Path(__file__).resolve().parent')
    code = code.replace('time.sleep(float(os.environ.get("UPGRADE_SLEEP", "0")))',
                        '(record.parent / "grandchild.pid").write_text(str(os.getpid()))\n'
                        '    time.sleep(1)\n'
                        '    (here / ".muse-version").write_text("late write")\n'
                        '    (record.parent / "late-write").touch()')
    driver.write_text(code)
    monkeypatch.setenv("FIXTURE_DRIVER", str(driver))
    monkeypatch.setenv("FIXTURE_LAUNCHER", str(launcher))
    monkeypatch.setenv("FIXTURE_INSTALL", str(install))
    launcher.write_text('''#!/bin/bash
set -euo pipefail
if [ "${MUSE_LAUNCHER_INSTALL:-0}" = 1 ]; then
  update_binary() (
    mkdir "$FIXTURE_INSTALL/.muse-update-lock"
    printf '%s\\n' "$$" >"$FIXTURE_INSTALL/.muse-update-lock/pid"
    printf '%s\\n' "$$" "$BASHPID" >"$HOME/installer.pids"
    python3 "$FIXTURE_DRIVER" "$@"
  )
  update_binary "$@"
else
  exec python3 "$FIXTURE_DRIVER" "$@"
fi
''')
    before = contents([root / "bin/muse", *install.iterdir()])
    fixture_step = update.step
    def timed_step(cmd, fh, env=None, timeout=update.STEP_CAP):
        return fixture_step(cmd, fh, env, .4 if cmd == muse()["upgrade"] else timeout)
    monkeypatch.setattr(update, "step", timed_step)
    try:
        rc, output = invoke()
        assert rc == 1, output
        assert "exit=timeout" in output
        assert "removed stale Muse installer lock" in output
        assert "muse: reverted" in output
        assert (root / "grandchild.pid").exists(), "the forked writer must have actually started"
        pids = [int(p) for p in (root / "installer.pids").read_text().split()]
        pids.append(int((root / "grandchild.pid").read_text()))
        for pid in pids:
            status = Path(f"/proc/{pid}/stat")
            assert not status.exists() or status.read_text().rsplit(")", 1)[1].split()[0] == "Z"
        time.sleep(1.1)
        assert not (root / "late-write").exists()
        assert contents(Path(p) for p in before) == before
        assert OLD in update.version(muse())
        assert not (install / ".muse-update-lock").exists()
        assert not list(config.TMP.glob("muse-snapshot-*"))
        assert gates == []
    finally:
        # A failing regression must clean up its writers without signalling a recycled PGID.
        if (root / "installer.pids").exists():
            pids = (root / "installer.pids").read_text().split()
            if (root / "grandchild.pid").exists():
                pids.append((root / "grandchild.pid").read_text())
            for pid in pids:
                try:
                    fd = os.pidfd_open(int(pid))
                except ProcessLookupError:
                    continue
                try:
                    env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
                    if f"FIXTURE_INSTALL={install}".encode() in env:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                except (FileNotFoundError, ProcessLookupError):
                    pass
                finally:
                    os.close(fd)


def test_failed_exit_does_not_signal_a_reaped_process_group(pinned_home, monkeypatch):
    def unexpected_signal(*args):
        pytest.fail("an exited/reaped child's PGID may belong to another process")
    monkeypatch.setattr(update.os, "killpg", unexpected_signal)
    with (pinned_home / "exit.log").open("w") as fh:
        assert not update.step(["/bin/sh", "-c", "exit 9"], fh)
    assert "[exit 9]" in (pinned_home / "exit.log").read_text()


def test_timeout_racing_a_completed_child_does_not_signal_its_reused_group(pinned_home, monkeypatch):
    proc = MagicMock()
    proc.__enter__.return_value = proc
    proc.__exit__.return_value = False
    proc.returncode = None
    proc.wait.side_effect = subprocess.TimeoutExpired(["fixture"], .1)
    # The process exited after wait's timeout; poll reaps it before a signal is sent.
    def reaped():
        proc.returncode = 9
        return 9
    proc.poll.side_effect = reaped
    monkeypatch.setattr(update.subprocess, "Popen", lambda *a, **kw: proc)
    signals = []
    monkeypatch.setattr(update.os, "killpg", lambda *a: signals.append(a))
    with (pinned_home / "timeout-race.log").open("w") as fh:
        assert not update.step(["fixture"], fh, timeout=.1)
    proc.poll.assert_called_once()
    assert not signals


@pytest.mark.parametrize("shape", ["directory", "hardlink", "unreadable", "foreign-owner", "external-link"])
def test_restore_replaces_failed_install_shapes_without_touching_link_targets(layout, monkeypatch, shape):
    root, install, _ = layout
    before = contents([root / "bin/muse", *install.iterdir()])
    canary = root / "unrelated-file"
    canary.write_text("leave this alone")
    def changed_gate(fh, log):
        path = install / ".muse-version"
        path.unlink()
        if shape == "directory":
            path.mkdir()
            (path / "new-build-file").write_text("failed install")
            extra = install / "muse-bin-unwanted"
            extra.mkdir()
            (extra / "payload").write_text("failed install")
        elif shape == "hardlink":
            os.link(canary, path)
        elif shape == "external-link":
            path.symlink_to(canary)
        else:
            path.write_text("failed install")
            if shape == "unreadable":
                path.chmod(0)
            else:
                # No root/chown requirement: report a foreign owner for the failed entry's
                # inode only, so the restored copy is still checked with its actual owner.
                inode = path.stat().st_ino
                real_lstat = Path.lstat
                def foreign_lstat(p):
                    info = real_lstat(p)
                    if p == path and info.st_ino == inode:
                        values = list(info)
                        values[4] = os.geteuid() + 1
                        return os.stat_result(values)
                    return info
                monkeypatch.setattr(Path, "lstat", foreign_lstat)
        return False, "offline gate failed after changing install shape"
    monkeypatch.setattr(update, "fresh_gate", changed_gate)
    rc, output = invoke()
    assert rc == 1, output
    assert "muse: reverted" in output
    assert contents(Path(p) for p in before) == before
    assert canary.read_text() == "leave this alone"
    assert set(install.iterdir()) == {Path(p) for p in before if Path(p).parent == install}
    assert not list(config.TMP.glob("muse-snapshot-*"))
