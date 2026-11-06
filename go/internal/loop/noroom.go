package loop

// A driver the host had no room to start a process for, Python's run.starved and run.end_starved:
// on 30 Oct 2026 a full task table ended 44 runs in `error` that a resume by hand carried on.  So
// where the driver would end its run in error it ends its process instead, the record reading as a
// loop that died, which the tick's dead-loop pass carries on.

import (
	"errors"
	"os"
	"runtime"
	"syscall"

	"agentkit/internal/run"
)

// noRoom is Python's log line of it, in Python's words: readers of the log match them.
const noRoom = "BlockingIOError(11, 'Resource temporarily unavailable'): no room to start a thread or process; the tick carries the run on"

// endNoRoom ends this driver at once, with sysexits' EX_TEMPFAIL, where err is a process the host
// had no room to start and its run is live, as End would have ended it in error: a run with no
// worktree yet reads as the slot wait it was, the one the dead-loop pass takes up with nothing to
// continue into.  A stop or an ending already written stands, for End.
func endNoRoom(dir string, err error) {
	if !errors.Is(err, syscall.EAGAIN) {
		return
	}
	live := false
	run.Change(dir, func(record *run.Object) error {
		if live = run.Active(record); live && !record.Truthy("worktree") {
			run.SetAll(record, "state", "queued", "slot_waiting", true)
		}
		return nil
	})
	if live {
		appendLog(dir, stamped(noRoom))
		os.Exit(75)
	}
}

// oneThreadAtATime lets one thread at a time run the driver's own code: it mostly waits on its
// children, so it loses no speed, and its runtime then wants no thread beyond those it holds when the
// task table fills, as one per core does for its garbage collector.  A thread Go's runtime fails to
// start kills the process, its record live but its log silent; held so, the next fork fails instead,
// as an error endNoRoom answers.  It takes fewer of the table's tasks too.
func oneThreadAtATime() { runtime.GOMAXPROCS(1) }
