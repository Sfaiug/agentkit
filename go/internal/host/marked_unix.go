//go:build unix

package host

import (
	"fmt"
	"io"
	"os"
	"slices"
	"strings"
	"syscall"
	"time"
)

const (
	endGrace  = 10 * time.Second // how long marked processes get to go quietly after TERM before KILL
	killGrace = 2 * time.Second  // how long a KILL gets to show
	endEvery  = 100 * time.Millisecond
)

// EndMarked ends every process carrying the run's marker, Python's worker.kill_marked: TERM to
// all of it, then KILL after a grace, each named in told.  What a run started is found by its
// environment, so nothing detached outlives the run, and found anew on every look: a process told
// to end can start another on its way out, which is told in turn.  One in its exec reads no
// environment until its new program's is in place, so it is looked at again.
func EndMarked(marker string, told io.Writer) {
	end(func() ([]int, bool) {
		found, silent := marking(marker)
		return found, slices.ContainsFunc(silent, execing)
	}, told)
}

// execing is whether a process whose environment read empty may still carry one.  An exec maps
// the new program's code, its stat's startcode, only once that program's environment is in place,
// so one without code is still in its exec, and one with it reads all it carries from then on.
func execing(pid int) bool {
	stat, ok := ReadStat(pid)
	fields := statFields("/proc", pid)
	// a kernel thread (PF_KTHREAD) has no code and no environment ever
	if !ok || stat.Exited() || stat.Flags&0x00200000 != 0 || len(fields) < 24 {
		return false
	}
	if fields[23] == "0" {
		return true
	}
	environ, err := os.ReadFile(fmt.Sprintf("/proc/%d/environ", pid))
	return err == nil && len(environ) > 0
}

// end is TERM to each process find finds, as it first finds it, then KILL after the grace to what
// is left, until a look finds none and nothing it could not judge.  The processes told are
// checked before each look: one gone had started all it ever will before the look began, so the
// look meets those.
func end(find func() (found []int, unsure bool), told io.Writer) {
	seen := map[int]int64{}
	left := func() (found []int, unsure bool) {
		for pid, start := range seen {
			if stat, ok := ReadStat(pid); ok && !stat.Exited() && stat.Start == start {
				found = append(found, pid)
			}
		}
		more, unsure := find()
		for _, pid := range more {
			stat, ok := ReadStat(pid)
			if start, known := seen[pid]; !ok || stat.Exited() || known && start == stat.Start {
				continue
			}
			seen[pid] = stat.Start
			said, _ := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
			fmt.Fprintf(told, "stopping process %d: %s\n", pid, strings.TrimSpace(strings.ReplaceAll(string(said), "\x00", " ")))
			syscall.Kill(pid, syscall.SIGTERM)
			found = append(found, pid)
		}
		return found, unsure
	}
	found, unsure := left()
	// the grace runs from the first TERMs, however long telling of them took
	for late := time.Now().Add(endGrace); (len(found) > 0 || unsure) && time.Now().Before(late); found, unsure = left() {
		time.Sleep(endEvery)
	}
	for late := time.Now().Add(killGrace); len(found) > 0 || unsure; found, unsure = left() {
		for _, pid := range found {
			syscall.Kill(pid, syscall.SIGKILL)
		}
		time.Sleep(endEvery)
		// only between looks, so all a look finds is KILLed and has had its pause to show
		if time.Now().After(late) {
			return
		}
	}
}

// Detached is what starts a program in a session of its own, so no terminal's signal reaches it.
func Detached() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setsid: true}
}

// Lower gives this process the priority a run's work has, Python's os.nice(10): a seat's turn and
// its terminal come first.  A priority it may not set is no reason to stop.
func Lower() {
	syscall.Setpriority(syscall.PRIO_PROCESS, 0, 10)
}
