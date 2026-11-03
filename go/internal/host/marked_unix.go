//go:build unix

package host

import (
	"fmt"
	"io"
	"os"
	"strings"
	"syscall"
	"time"
)

const (
	killGrace = 2 * time.Second // how long a KILL gets to show
	endEvery  = 100 * time.Millisecond
)

// endGrace is how long marked processes get to go quietly after TERM before KILL.
var endGrace = 10 * time.Second

// EndMarked ends every process carrying the run's marker, Python's worker.kill_marked: TERM to
// all of it, then KILL after a grace, each named in told.  What a run started is found by its
// environment, so nothing detached outlives the run, and found anew on every look: a process told
// to end can start another on its way out.
func EndMarked(marker string, told io.Writer) {
	end(func() []int { return Marked(marker) }, told)
}

// end is TERM to every process find finds, then KILL after the grace.
func end(find func() []int, told io.Writer) {
	seen := map[int]int64{}
	left := func() (found []int) {
		for _, pid := range find() {
			if stat, ok := ReadStat(pid); ok {
				seen[pid] = stat.Start
			}
		}
		for pid, start := range seen {
			if stat, ok := ReadStat(pid); ok && !stat.Exited() && stat.Start == start {
				found = append(found, pid)
			}
		}
		return found
	}
	for _, pid := range left() {
		said, _ := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
		fmt.Fprintf(told, "stopping process %d: %s\n", pid, strings.TrimSpace(strings.ReplaceAll(string(said), "\x00", " ")))
		syscall.Kill(pid, syscall.SIGTERM)
	}
	for late := time.Now().Add(endGrace); time.Now().Before(late) && len(left()) > 0; {
		time.Sleep(endEvery)
	}
	for late := time.Now().Add(killGrace); time.Now().Before(late); time.Sleep(endEvery) {
		marked := left()
		if len(marked) == 0 {
			return
		}
		for _, pid := range marked {
			syscall.Kill(pid, syscall.SIGKILL)
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
