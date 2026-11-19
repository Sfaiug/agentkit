"""Machines for a standby's keys (tests/fixtures/twohomes.py): two on the one the test runs on,
alike, each with a host name, a home at the other's path, a /tmp, fakes, variables, a cgroup
root and an ak install of its own, and each reaching the other by ssh as the key and the tick
reach it; a third where a key names one; one a key holds made the other's client, silent or
hanging; and their installs' one origin, which a fetch reaches from either, the other silent,
and a push of a ref under refs/agentkit/ too, by compare-and-swap, which a key reads and writes;
and that origin broken, for one machine or both, each way a remote fails, and mended."""

from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import _end, boxable
from fixtures.akinstall import ORIGIN, agentkit_refs
from fixtures.twohomes import Machines

REFUSED = "systemctl: not scripted in this test\n"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class TwoHomes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machines = Machines("acme-mini", "acme-vm")
        cls.addClassCleanup(cls.machines.close)
        mini, vm = cls.machines
        cls.pairs = ((mini, vm), (vm, mini))    # each machine with the other

    def test_each_is_its_host_name_and_reaches_the_other_by_it(self):
        for machine, other in self.pairs:
            for argv in (["hostname"],
                         [sys.executable, "-c", "import socket; print(socket.gethostname())"]):
                self.assertEqual(machine.run(*argv).out, f"{machine.name}\n")
            done = machine.run("ssh", "-o", "BatchMode=yes", "-T", other.name, "hostname")
            self.assertEqual((done.code, done.out), (0, f"{other.name}\n"))
            self.assertEqual(machine.run("ssh", "acme-nas", "hostname").code, 255)
            # git's fetch of the origin, and nothing else, reaches it
            self.assertEqual(machine.run("ssh", "git@github.com", "hostname").code, 255)

    def test_a_command_of_any_length_reaches_the_other_whole(self):
        for machine, other in self.pairs:
            done = machine.run("ssh", other.name, f"printf %s {'x' * 70000} | wc -c", timeout=30)
            self.assertEqual((done.code, done.out.strip()), (0, "70000"), done.err)

    def test_each_has_its_own_files_at_the_one_home(self):
        homes = {machine.run("sh", "-c", 'echo "$HOME"; pwd').out for machine in self.machines}
        self.assertEqual(len(homes), 1, homes)
        self.assertEqual(len(set(homes.pop().split())), 1, "a command starts in its home")
        for machine, other in self.pairs:
            for file in (f"~/from-{machine.name}", f"/tmp/from-{machine.name}"):
                self.assertEqual(machine.run("sh", "-c", f"hostname >{file}").code, 0)
                self.assertNotEqual(other.run("sh", "-c", f"cat {file}").code, 0, file)
                done = other.run("ssh", machine.name, f"cat {file}")
                self.assertEqual(done.out, f"{machine.name}\n", done.err)
            # the test's side of a machine's home is no path on any machine, its own included
            kept = machine.write(f"kept-{machine.name}", "acme\n")
            self.assertEqual(machine.run("cat", kept.name).out, "acme\n")
            for each in self.machines:
                self.assertNotEqual(each.run("cat", kept).code, 0)
                self.assertNotEqual(each.run("ssh", machine.name, f"cat {kept}").code, 0)

    def test_a_fake_is_on_its_machine_alone(self):
        mini, vm = self.machines
        mini.fake("acme-sync", "#!/bin/sh\necho \"acme-sync on $(hostname)\"\n")
        for done in (mini.run("acme-sync"), vm.run("ssh", mini.name, "acme-sync")):
            self.assertEqual(done.out, "acme-sync on acme-mini\n", done.err)
        self.assertNotEqual(vm.run("sh", "-c", "command -v acme-sync").code, 0)

    def each_way(self, machine, other, line):
        """What the shell `line` prints on `machine`, started each way: by the key, by that
        machine's tick, in the program's place, and over ssh from `other`."""
        machine.fake("acme-line", f"#!/bin/sh\n{line}\n")
        ways = (machine.run("acme-line"),
                machine.tick(box=("--ro-bind", machine.at / "bin" / "acme-line",
                                  machine.program)),
                other.run("ssh", machine.name, "acme-line"))
        return [done.out for done in ways]

    def test_a_variable_set_for_one_machine_reaches_what_runs_there_alone(self):
        mini, _ = self.machines
        mini.env["ACME_CLOCK"] = "10000"
        self.addCleanup(mini.env.pop, "ACME_CLOCK")
        for machine, other in self.pairs:
            told = "10000\n" if machine is mini else "unset\n"
            self.assertEqual(self.each_way(machine, other, 'echo "${ACME_CLOCK-unset}"'),
                             [told] * 3)

    def test_each_has_a_cgroup_root_of_its_own_an_empty_folder_outside_its_home(self):
        for machine, other in self.pairs:
            root = machine.env["AK_CGROUP_ROOT"]
            self.assertFalse(Path(root).is_relative_to(machine.env["HOME"]), root)
            slice_ = other.root / "cgroups" / "acme.slice"
            slice_.mkdir()      # the other's reaches it no more than the host's does
            seen = self.each_way(machine, other, 'cd "$AK_CGROUP_ROOT" && pwd -P && ls -A')
            slice_.rmdir()
            self.assertEqual(seen, [f"{root}\n"] * 3)

    def test_a_host_tool_is_refused_on_either_side_of_ssh(self):
        for machine, other in self.pairs:
            for done in (machine.run("systemctl", "--user", "start", "acme"),
                         other.run("ssh", machine.name, "systemctl --user start acme")):
                self.assertEqual((done.code, done.err), (1, REFUSED))
        for machine in self.machines:
            self.assertEqual(machine.calls("systemctl"), [["--user", "start", "acme"]] * 2)

    def test_ak_runs_on_each_and_a_tick_writes_in_its_own_home(self):
        mini, vm = self.machines
        for machine in self.machines:
            done = machine.ak("doctor", "-h")
            self.assertEqual(done.code, 0, done.err)
        config = mini.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        theirs = vm.tree()
        done = mini.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn(".agentkit/state/watch.json", mini.tree())
        self.assertEqual(vm.tree(), theirs)

    def test_either_is_made_the_others_client(self):
        mini, vm = self.machines
        records = [machine.path / ".agentkit" / "state" / "server" for machine in self.machines]
        for record in records:      # the other tests tick on no one's client
            self.addCleanup(record.unlink, missing_ok=True)
        vm.client_of(mini)
        mini.client_of(vm)      # turned round
        self.assertEqual([record.read_text() if record.exists() else None for record in records],
                         ["acme-vm\n", None])

    def test_a_silent_machine_is_off_till_it_answers(self):
        mini, vm = self.machines
        self.addCleanup(vm.answer)
        pid = int(vm.run("sh", "-c", "sleep 600 >/dev/null 2>&1 & echo $!").out)
        vm.silence()
        self.assertEqual(mini.run("ssh", vm.name, "touch ran").code, 255)
        self.assertRaises(OSError, vm.run, "touch", "ran")
        self.assertFalse((vm.path / "ran").exists())
        self.assertRaises(ProcessLookupError, os.kill, pid, 0)
        vm.answer()
        done = mini.run("ssh", vm.name, "hostname")
        self.assertEqual((done.code, done.out), (0, "acme-vm\n"), done.err)

    def test_a_hanging_machine_takes_ssh_and_runs_nothing_till_it_answers(self):
        mini, vm = self.machines
        self.addCleanup(vm.answer)
        vm.hang()
        with self.assertRaisesRegex(AssertionError, "still running after 2 s"):
            mini.run("ssh", vm.name, "touch ran", timeout=2)     # which ends it
        self.assertFalse((vm.path / "ran").exists())
        vm.answer()
        done = mini.run("ssh", vm.name, "hostname")
        self.assertEqual((done.code, done.out), (0, "acme-vm\n"), done.err)

    def test_each_has_an_install_on_main_of_the_one_origin_that_is_no_machine(self):
        for machine in self.machines:
            install = machine.install
            self.assertEqual(install.git("rev-parse", "--abbrev-ref", "HEAD"), "main")
            self.assertEqual(install.git("remote", "get-url", "origin"), ORIGIN)
            self.assertEqual(install.head(), install.origin())
            for each in self.machines:
                self.assertNotEqual(each.run("ls", install.bare).code, 0)

    def test_a_fetch_on_either_brings_the_next_commit_and_moves_no_install(self):
        with Machines("acme-mini", "acme-vm") as (mini, vm):
            start, tip = mini.install.head(), vm.install.advance()
            for machine in (mini, vm):
                machine.install.git("fetch", "-q", "origin")
                self.assertEqual(machine.install.git("rev-parse", "origin/main"), tip)
                self.assertEqual((machine.install.head(), machine.install.installs()), (start, 0))
            vm.silence()
            tip = mini.install.advance()
            mini.install.git("fetch", "-q", "origin")
            self.assertEqual(mini.install.git("rev-parse", "origin/main"), tip)

    @staticmethod
    def commit_on(machine):
        """A commit made in `machine`'s install, naming it, that no remote holds yet."""
        return machine.install.git("-c", "user.name=acme", "-c", "user.email=acme@example.com",
                                   "commit-tree", "-m", machine.name, "HEAD^{tree}")

    @staticmethod
    def read(machine):
        """The refs under refs/agentkit/ that `machine` reads on its install's remote, each once:
        `--refs` lists no peeled `^{}` line beside a tag's."""
        return agentkit_refs(machine.install.git("ls-remote", "--refs", "origin", raw=True))

    @staticmethod
    def push(machine, ref, old, value):
        """Push `value` to `ref` from `machine`'s install if the remote's `ref` names `old`, None
        when absent, as a machine takes a lease."""
        return machine.run("git", "-C", machine.install.at, "push", "-q",
                           f"--force-with-lease={ref}:{old or ''}", "origin", f"{value}:{ref}")

    def test_a_ref_one_pushes_is_what_the_other_and_the_key_read(self):
        install, pushed = self.machines[0].install, {}
        for machine, other in self.pairs:
            ref, made = f"refs/agentkit/{machine.name}", self.commit_on(machine)
            self.addCleanup(install.set_ref, ref, None)
            machine.install.git("push", "-q", "origin", f"{made}:{ref}")
            pushed[ref] = made
            self.assertEqual((self.read(other), install.refs()), (pushed, pushed))
            held = machine.install.git("cat-file", "commit", made, raw=True)
            self.assertEqual(install.commit(made), held)    # whole, its last line break too

    def test_of_two_pushes_naming_one_old_value_one_is_refused(self):
        install, ref = self.machines[0].install, "refs/agentkit/home"
        old = install.origin()
        install.set_ref(ref, old)
        self.addCleanup(install.set_ref, ref, None)
        made = {machine.name: self.commit_on(machine) for machine in self.machines}
        with ThreadPoolExecutor() as pool:      # both at once, as two machines taking one lease
            codes = dict(zip(made, pool.map(
                lambda machine: self.push(machine, ref, old, made[machine.name]).code,
                self.machines)))
        self.assertEqual(sorted(code == 0 for code in codes.values()), [False, True], codes)
        won = next(name for name, code in codes.items() if code == 0)
        self.assertEqual(install.refs(), {ref: made[won]})

    def test_a_keys_change_of_a_ref_and_its_delete_are_what_each_machine_reads(self):
        mini, vm = self.machines
        install, ref, made = mini.install, "refs/agentkit/home", self.commit_on(mini)
        self.addCleanup(install.set_ref, ref, None)
        mini.install.git("push", "-q", "origin", f"{made}:{ref}")
        for value, read in ((install.origin(), {ref: install.origin()}), (None, {})):
            install.set_ref(ref, value)
            self.assertEqual([self.read(machine) for machine in self.machines], [read] * 2)

    def broken(self, how, *machines, value=None):
        """The machines' origin broken `how` for `machines`, or both, till the test ends; the ref
        the test reads and writes there, absent then too."""
        install, ref = self.machines[0].install, "refs/agentkit/home"
        self.addCleanup(install.set_ref, ref, None)
        self.addCleanup(self.machines.mend_remote)
        self.machines.break_remote(how, *machines, value=value)
        return install, ref

    def test_an_unreachable_remote_fails_each_way_for_its_machine_alone_till_mended(self):
        mini, vm = self.machines
        _, ref = self.broken("unreachable", mini)
        # a read, then a push of a fresh commit naming the value read, each saying it got through
        line = (f'cd "$HOME/agentkit"; read=$(git ls-remote origin {ref}) && echo read; '
                f'git push -q "--force-with-lease={ref}:${{read%%[[:space:]]*}}" origin '
                f'"$(git commit-tree -m "after $read" "HEAD^{{tree}}"):{ref}" && echo pushed')
        self.assertEqual(self.each_way(mini, vm, line), [""] * 3)
        self.assertEqual(self.each_way(vm, mini, line), ["read\npushed\n"] * 3)
        self.machines.mend_remote()
        for machine, other in self.pairs:
            self.assertEqual(self.each_way(machine, other, line), ["read\npushed\n"] * 3)

    def test_a_silent_remote_holds_a_push_past_its_mend_till_the_test_ends_it(self):
        mini, _ = self.machines
        install, ref = self.broken("silent")
        made = self.commit_on(mini)
        argv = ["git", "-C", mini.install.at, "push", "-q", f"--force-with-lease={ref}:",
                "origin", f"{made}:{ref}"]
        waiting = mini._popen(argv, None, None, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(_end, waiting)
        self.assertTrue(mini.held.acquire(timeout=60), "the remote took no call")
        with self.assertRaises(subprocess.TimeoutExpired):
            waiting.wait(timeout=2)
        self.assertEqual(install.refs(), {})
        self.machines.mend_remote()
        done = self.push(mini, ref, None, made)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(install.refs(), {ref: made})
        self.assertIsNone(waiting.poll())

    def test_a_lost_answer_fails_a_push_the_remote_keeps(self):
        mini, _ = self.machines
        install, ref = self.broken("lost")
        made = self.commit_on(mini)
        self.assertNotEqual(self.push(mini, ref, None, made).code, 0)
        self.assertEqual(install.refs(), {ref: made})

    def test_a_write_that_comes_between_refuses_that_machines_next_push_alone(self):
        mini, vm = self.machines
        between = mini.install.origin()
        install, ref = self.broken("between", mini, value=between)
        theirs, mine = self.commit_on(vm), self.commit_on(mini)
        self.assertEqual(self.push(vm, ref, None, theirs).code, 0)    # vm's push meets none
        read = self.read(mini)[ref]
        self.assertNotEqual(self.push(mini, ref, read, mine).code, 0)
        self.assertEqual(install.refs(), {ref: between})
        done = self.push(mini, ref, between, mine)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(install.refs(), {ref: mine})

    def test_a_tick_moves_the_install_it_runs_from_alone(self):
        with Machines("acme-mini", "acme-vm") as (mini, vm):
            akconfig.write(mini, ["opus"])
            start, tip = vm.install.head(), mini.install.advance()
            done = mini.tick()
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual((mini.install.head(), mini.install.installs()), (tip, 1))
            self.assertEqual((vm.install.head(), vm.install.installs()), (start, 0))

    def test_a_third_machine_a_key_names_reaches_both_and_is_reached_by_both(self):
        with Machines("acme-mini", "acme-vm", "acme-laptop") as (*pair, laptop):
            for each in pair:
                for machine, other in ((laptop, each), (each, laptop)):
                    done = machine.run("ssh", other.name, "hostname")
                    self.assertEqual((done.code, done.out), (0, f"{other.name}\n"), done.err)
            self.assertEqual(laptop.run("ssh", "acme-nas", "hostname").code, 255)

    def test_a_home_put_elsewhere_is_where_its_own_machine_alone_finds_it(self):
        with Machines("acme-mini", "acme-mac", homes={"acme-mac": "Users/acme"}) as (mini, mac):
            self.assertEqual(mac.env["HOME"], str(mac.at / "Users" / "acme"))
            for machine, other in ((mini, mac), (mac, mini)):
                home = machine.env["HOME"]
                done = other.run("ssh", machine.name, 'echo "$HOME"; pwd; cat agentkit/notes')
                self.assertEqual(done.out, f"{home}\n{home}\nnotes\n", done.err)
                self.assertNotEqual(other.run("ls", home).code, 0)

    def test_a_process_ends_with_its_machine_alone_whatever_its_environment_keeps(self):
        # its machine's tmux dir is the one variable a machine's commands hold alone
        with Machines("acme-mini", "acme-vm") as (mini, vm):
            done = vm.run("sh", "-c", "env -u TMUX_TMPDIR setsid sleep 60 "
                                      "</dev/null >/dev/null 2>&1 & echo $!")
            pid = int(done.out)
            mini.close()
            os.kill(pid, 0)     # still running
            vm.close()
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)


if __name__ == "__main__":
    unittest.main()
