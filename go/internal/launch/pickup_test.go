//go:build linux

package launch

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// A launch waiting for its slot moves to the installed ak when that moves: first in line it says
// so and execs the same launch there, which takes up the same receipt, the pid and queued_at kept,
// and waits on; behind the first its waiter execs the same launch back there, which goes back to a
// waiter, the pid kept.  The installed ak is a copy of this program, each install a new file, and
// its version a fake git's answer for the folder above its bin/.
func TestAQueuedLaunchMovesToTheInstalledAk(t *testing.T) {
	home := queuedHome(t)
	t.Setenv("AK_SLOT_POLL", "0.5")
	held(t, "held")
	self, _, err := config.Running()
	program, look := os.ReadFile(self)
	real, found := exec.LookPath("git")
	if err != nil || look != nil || found != nil {
		t.Fatal(err, look, found)
	}
	ak, version, fakes := filepath.Join(t.TempDir(), "bin", "ak"), filepath.Join(home, "version"), t.TempDir()
	install := func(head string) {
		write(t, ak+".new", string(program))
		write(t, version+".new", head+"\n")
		for _, path := range []string{ak, version} {
			if err := os.Rename(path+".new", path); err != nil {
				t.Fatal(err)
			}
		}
	}
	install("aaa1111")
	write(t, filepath.Join(fakes, "git"), "#!/bin/sh\n"+
		"if [ \"$#\" = 5 ] && [ \"$1\" = -C ] && [ \"$2\" = '"+filepath.Dir(filepath.Dir(config.Resolve(ak)))+"' ] && [ \"$3 $4 $5\" = 'rev-parse --short HEAD' ]; then\n"+
		"    exec cat '"+version+"'\nfi\nexec '"+real+"' \"$@\"\n")
	t.Setenv("PATH", fakes+string(os.PathListSeparator)+os.Getenv("PATH"))

	launched := map[string]*run.Object{"acme": waiter(t, "acme", time.Minute, died(t), ""), "later": waiter(t, "later", time.Second, died(t), "")}
	pids := map[string]int{"acme": driven(t, "acme", ak), "later": driven(t, "later", ak)}
	logged := func(id string) string {
		data, _ := os.ReadFile(filepath.Join(run.Runs(), id, "log.txt"))
		return string(data)
	}
	until := func(what string, done func() bool) {
		t.Helper()
		for deadline := time.Now().Add(30 * time.Second); !done(); time.Sleep(20 * time.Millisecond) {
			if time.Now().After(deadline) {
				t.Fatalf("never: %s\nacme logged %q\nlater logged %q", what, logged("acme"), logged("later"))
			}
		}
	}
	// whether the process runs the ak installed now, and as a run's waiter
	installedNow := func(pid int) bool {
		running, err := os.Stat(fmt.Sprintf("/proc/%d/exe", pid))
		now, _ := os.Stat(ak)
		return err == nil && now != nil && os.SameFile(running, now)
	}
	waiting := func(pid int) bool {
		said, _ := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
		return strings.HasPrefix(string(said), waiterName+"\x00")
	}
	const waits = "waiting for a slot · limit full (1 running) · 0 ahead\n"

	until("acme waiting first in line and later in its waiter", func() bool {
		return strings.HasSuffix(logged("acme"), waits) && waiting(pids["later"])
	})
	install("bbb2222")
	until("both on the ak installed now, later in its waiter again", func() bool {
		after := strings.SplitN(logged("acme"), " picked up agentkit aaa1111..bbb2222 while waiting for a slot\n", 2)
		return len(after) == 2 && strings.HasSuffix(after[1], waits) && installedNow(pids["acme"]) &&
			installedNow(pids["later"]) && waiting(pids["later"])
	})
	for id, receipt := range launched {
		record, _ := run.Read(filepath.Join(run.Runs(), id))
		pid, _ := record.Int("pid")
		at, _ := record.Num("queued_at")
		was, _ := receipt.Num("queued_at")
		if record.Str("state") != "queued" || !record.Truthy("slot_waiting") || at != was || pid != pids[id] || !run.ProcessActive(record) {
			t.Fatalf("%s's receipt: %s", id, run.Line(record))
		}
	}
	if line, _ := queued(); strings.Join(line.queue, " ") != "acme later" {
		t.Fatalf("the line: %v", line.queue)
	}
}

// driven is the pid of the driver program starts for the queued run id, writing to its log and
// named on its receipt before it reads it, as loop.Start names one; ended before its HOME goes.
func driven(t *testing.T, id, program string) (pid int) {
	dir := filepath.Join(run.Runs(), id)
	err := run.Change(dir, func(record *run.Object) error {
		log, err := os.OpenFile(filepath.Join(dir, "log.txt"), os.O_WRONLY|os.O_APPEND, 0)
		if err != nil {
			return err
		}
		defer log.Close()
		driver := exec.Command(program, "run", loop.DriveFlag, dir)
		driver.Stdout, driver.Stderr = log, log
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
