package launch

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/run"
)

// A run behind the first in line for its slot, who alone can be let in, waits in a process holding
// next to no memory, as Python's waiter: its driver execs this program again as its waiter, keeping
// its pid and so its receipt and its place in line.  The waiter reads only runs/.slots.queue and the
// installed version, opens no SQLite, and execs the driver back on the installed ak once the run is
// no longer behind the first, the queue is stale for its place (behindFirst), or the installed
// version moved (pickUp).  Without exec (Windows) the run waits in its driver.

// waiterName is the waiter's argv[0], which nobody types; the driver's own words follow it, so its
// command line still names the run's driver (loop.driving).
const waiterName = "ak-slot-waiter"

// slotWait is in the waiter's environment, and so in the driver it execs back: the polls that
// driver skipped were count waits, as Python's AK_SLOT_WAIT says.  Go counts no wait in history
// (run.Historyless), so it carries no count, but the driver's own GODEBUG, which the waiter's
// replaces (lean).
const slotWait = "AK_SLOT_WAIT"

// lean is the waiter's GODEBUG: its heap takes no transparent huge pages, which a host giving them
// by default pads it with, 6.9 MB held where 3.8 do: too near a third of the first in line's 23.
const lean = "disablethp=1"

// becomeWaiter replaces the run's driver with its waiter.  It returns only where it cannot or may
// not (movable), or the system has no exec.
func becomeWaiter(dir string, record *run.Object) {
	self, err := os.Executable()
	if err != nil || !movable(dir, record) {
		return
	}
	syscall.Exec(self, append([]string{waiterName}, os.Args[1:]...), append(debugged(lean), slotWait+"="+os.Getenv("GODEBUG")))
}

// debugged is this process's environment with GODEBUG that, or none for "".
func debugged(debug string) []string {
	env := slices.DeleteFunc(os.Environ(), func(each string) bool { return strings.HasPrefix(each, "GODEBUG=") })
	if debug != "" {
		env = append(env, "GODEBUG="+debug)
	}
	return env
}

// cameBack is whether a waiter execed this driver back, taking the word out of the environment
// so nothing the driver starts inherits it.
func cameBack() bool {
	_, back := os.LookupEnv(slotWait)
	os.Unsetenv(slotWait)
	return back
}

// Waiter is this process as a run's waiter, true where it is one.  It returns only where it cannot
// exec the driver back, leaving the run queued for the tick to take up.
func Waiter() (int, bool) {
	if len(os.Args) != 4 || os.Args[0] != waiterName {
		return 0, false
	}
	id := filepath.Base(os.Args[3])
	poll, _ := slotPoll()
	_, on := installed()
	for behindFirst(id, poll) {
		time.Sleep(untilTurn(id, poll))
		if _, now := moved(on); now != "" {
			break
		}
	}
	self, err := os.Executable()
	if err == nil {
		err = syscall.Exec(self, append([]string{self}, os.Args[1:]...), debugged(os.Getenv(slotWait)))
	}
	fmt.Fprintln(os.Stderr, "ak: the slot waiter cannot start its driver again:", err)
	return 1, true
}

// untilTurn is how long the waiter sleeps until its place's share of the poll comes round, Python's
// waiter.offset: waiters at different places poll at different moments, so those started together
// never poll all at once.  A whole poll where the line does not list the run.
func untilTurn(id string, poll float64) time.Duration {
	saved, _ := queued()
	wait := poll
	if place := slices.Index(saved.queue, id); place >= 0 {
		wait -= math.Mod(now()-poll*float64(place)/float64(len(saved.queue)), poll)
	}
	return time.Duration(wait * float64(time.Second))
}
