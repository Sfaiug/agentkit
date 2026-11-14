//go:build linux

package launch

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/unix"

	"agentkit/internal/config"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// A launch waiting for its slot moves to the installed ak when that moves, from the version it read
// as it began to wait, before a poll could hold it up: first in line it says so and execs the same
// launch there, which takes up the same receipt, the pid and queued_at kept; behind the first it
// goes to its waiter there, and the waiter execs the same launch back as the install moves again.
// A driver no AGENTKIT_RUN_DIR names as its run's own, or pinned to a checkout (ak_checkout), never
// moves.  The installed ak is a checkout holding a copy of this program, each install a new checkout
// swapped in whole, as ak's update swaps them, and its version a fake git's answer for the folder
// above its bin/, which logs who read what.
func TestAQueuedLaunchMovesToTheInstalledAk(t *testing.T) {
	home := queuedHome(t)
	t.Setenv("AK_SLOT_POLL", "0.5")
	held(t, "held")
	self, err := os.Executable()
	program, look := os.ReadFile(self)
	real, found := exec.LookPath("git")
	if err != nil || look != nil || found != nil {
		t.Fatal(err, look, found)
	}
	checkout, reads, fakes := t.TempDir(), filepath.Join(home, "reads"), t.TempDir()
	ak := filepath.Join(checkout, "bin", "ak")
	write(t, ak, string(program))
	write(t, filepath.Join(checkout, "version"), "aaa1111\n")
	first, err := os.Stat(ak)
	if err != nil {
		t.Fatal(err)
	}
	install := func(head string) {
		next := t.TempDir()
		write(t, filepath.Join(next, "bin", "ak"), string(program))
		write(t, filepath.Join(next, "version"), head+"\n")
		if err := unix.Renameat2(unix.AT_FDCWD, checkout, unix.AT_FDCWD, next, unix.RENAME_EXCHANGE); err != nil {
			t.Fatal(err)
		}
	}
	write(t, filepath.Join(fakes, "git"), "#!/bin/sh\n"+
		"if [ \"$#\" = 5 ] && [ \"$1\" = -C ] && [ \"$2\" = '"+config.Resolve(checkout)+"' ] && [ \"$3 $4 $5\" = 'rev-parse --short HEAD' ]; then\n"+
		"    version=$(cat \"$2/version\") as=driver\n"+
		"    [ \"$(tr '\\000' '\\n' < /proc/$PPID/cmdline | head -n 1)\" = "+waiterName+" ] && as=waiter\n"+
		"    echo \"$PPID $as $version\" >> '"+reads+"'\n"+
		"    echo \"$version\"\n    exit 0\nfi\nexec '"+real+"' \"$@\"\n")
	t.Setenv("PATH", fakes+string(os.PathListSeparator)+os.Getenv("PATH"))

	launched := map[string]*run.Object{}
	pids := map[string]int{}
	slots, err := holdSlots()
	if err != nil {
		t.Fatal(err)
	}
	order := []string{"acme", "later", "fore", "other", "pinned"}
	for at, id := range order {
		dir := filepath.Join(run.Runs(), id)
		launched[id] = waiter(t, id, time.Duration(len(order)-at)*time.Minute, died(t), "")
		if id == "pinned" {
			if err := run.Change(dir, func(r *run.Object) error { r.Set("ak_checkout", checkout); return nil }); err != nil {
				t.Fatal(err)
			}
		}
		marker := dir
		switch id {
		case "fore":
			marker = ""
		case "other":
			marker = filepath.Join(run.Runs(), "acme")
		}
		pids[id] = driven(t, id, ak, marker)
	}
	logged := func(id string) string {
		data, _ := os.ReadFile(filepath.Join(run.Runs(), id, "log.txt"))
		return string(data)
	}
	read := func(id, as, head string) bool {
		data, _ := os.ReadFile(reads)
		return strings.Contains(string(data), fmt.Sprintf("%d %s %s\n", pids[id], as, head))
	}
	until := func(what string, done func() bool) {
		t.Helper()
		for deadline := time.Now().Add(time.Minute); !done(); time.Sleep(20 * time.Millisecond) {
			if time.Now().After(deadline) {
				said, _ := os.ReadFile(reads)
				t.Fatalf("never: %s\nacme logged %q\nreads %q", what, logged("acme"), said)
			}
		}
	}
	// whether the run's process runs the ak installed now
	current := func(id string) bool {
		running, err := os.Stat(fmt.Sprintf("/proc/%d/exe", pids[id]))
		now, _ := os.Stat(ak)
		return err == nil && now != nil && os.SameFile(running, now)
	}
	waiting := func(id string) bool {
		said, _ := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pids[id]))
		return strings.HasPrefix(string(said), waiterName+"\x00")
	}
	moves := func(from, to string) func() bool {
		return func() bool {
			after := strings.SplitN(logged("acme"), " picked up agentkit "+from+".."+to+" while waiting for a slot\n", 2)
			// what holds it, said by the process it execed as that one polled, which read its version first
			return len(after) == 2 && strings.HasSuffix(after[1], "waiting for a slot · limit full (1 running) · 0 ahead\n") && current("acme")
		}
	}

	until("each driver read the version it begins to wait on", func() bool {
		for _, id := range order {
			if !read(id, "driver", "aaa1111") {
				return false
			}
		}
		return true
	})
	install("bbb2222") // while each first poll waits for the slots lock
	slots.Close()
	until("acme moved to bbb2222, later waiting there", func() bool {
		return moves("aaa1111", "bbb2222")() && waiting("later") && current("later") && read("later", "waiter", "bbb2222")
	})
	install("ccc3333")
	until("acme moved again, from the version its new process began to wait on", moves("bbb2222", "ccc3333"))
	until("later's waiter moved to ccc3333", func() bool { return waiting("later") && current("later") })

	for id, receipt := range launched {
		record, _ := run.Read(filepath.Join(run.Runs(), id))
		pid, _ := record.Int("pid")
		at, _ := record.Num("queued_at")
		was, _ := receipt.Num("queued_at")
		if record.Str("state") != "queued" || !record.Truthy("slot_waiting") || at != was || pid != pids[id] || !run.ProcessActive(record) {
			t.Fatalf("%s's receipt: %s", id, run.Line(record))
		}
	}
	if line, _ := queued(); strings.Join(line.queue, " ") != strings.Join(order, " ") {
		t.Fatalf("the line: %v", line.queue)
	}
	for _, id := range []string{"fore", "other", "pinned"} {
		if running, err := os.Stat(fmt.Sprintf("/proc/%d/exe", pids[id])); err != nil || !os.SameFile(running, first) || waiting(id) {
			t.Fatalf("%s left the ak it started on: %v", id, err)
		}
	}
}

// driven is the pid of the driver program starts for the queued run id, writing to its log, named
// on its receipt before it reads it, as loop.Start names one, with AGENTKIT_RUN_DIR set to marker
// where non-empty; ended before its HOME goes.
func driven(t *testing.T, id, program, marker string) (pid int) {
	dir := filepath.Join(run.Runs(), id)
	err := run.Change(dir, func(record *run.Object) error {
		log, err := os.OpenFile(filepath.Join(dir, "log.txt"), os.O_WRONLY|os.O_APPEND, 0)
		if err != nil {
			return err
		}
		defer log.Close()
		driver := exec.Command(program, "run", loop.DriveFlag, dir)
		driver.Stdout, driver.Stderr = log, log
		driver.Env = slices.DeleteFunc(os.Environ(), func(pair string) bool {
			return strings.HasPrefix(pair, "AGENTKIT_RUN_DIR=")
		})
		if marker != "" {
			driver.Env = append(driver.Env, "AGENTKIT_RUN_DIR="+marker)
		}
		if err := driver.Start(); err != nil {
			return err
		}
		t.Cleanup(func() {
			driver.Process.Kill()
			driver.Wait()
		})
		pid = driver.Process.Pid
		run.SetAll(record, "pid", pid, "process_identity", loop.Identity(pid))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return pid
}
