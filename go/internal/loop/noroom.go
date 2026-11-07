package loop

// A driver the host had no room to start a process for, Python's run.starved and run.end_starved:
// on 30 Oct 2026 a full task table ended 44 runs in `error` that a resume by hand carried on.  So
// where the driver would end its run in error it ends its process instead, the record reading as a
// loop that died, which the tick's dead-loop pass carries on.

import (
	"errors"
	"os"
	"os/exec"
	"runtime"
	"sync"
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

// heldThreads is how many threads holdThreads parks: one for each of all but one of the driver's
// calls that block at once, and one for the turn the last of them hands off.
const heldThreads = 8

// holdThreads has the driver's runtime start, before the task table can fill, the threads it later
// wants: a thread Go's runtime fails to start kills the process, its record live but its log
// silent; held so, the next fork fails instead, as an error endNoRoom answers.  Where the table
// has no room for them already, the processes taskRoom starts first fail so, and it returns that
// error before any thread.  One thread at a time runs the driver's own code, which mostly waits on
// its children and so loses no speed, and its garbage collector wants no thread per core.  But a
// call that blocks hands that turn to another thread, one the runtime starts where none is parked:
// heldThreads goroutines, each locked to a thread of its own until all are, leave as many parked
// for the process's life once they let go.
func holdThreads() error {
	runtime.GOMAXPROCS(1)
	// the threads it locks, and the one the runtime starts threads from once one is locked
	if err := taskRoom(heldThreads + 1); errors.Is(err, syscall.EAGAIN) {
		return err
	}
	var held, freed sync.WaitGroup
	held.Add(heldThreads)
	freed.Add(heldThreads)
	for range heldThreads {
		go func() {
			defer freed.Done()
			runtime.LockOSThread()
			held.Done()
			held.Wait()
			runtime.UnlockOSThread()
		}()
	}
	freed.Wait()
	return nil
}

// taskRoom is the host's room for n more tasks, a process or thread each, proven by as many
// processes at once: each waits on a pipe this one closes once all have started, or one failed to.
func taskRoom(n int) error {
	r, w, err := os.Pipe()
	if err != nil {
		return err
	}
	defer r.Close()
	var started []*exec.Cmd
	defer func() {
		w.Close()
		for _, held := range started {
			held.Wait()
		}
	}()
	for range n {
		held := exec.Command("cat")
		held.Stdin = r
		if err := held.Start(); err != nil {
			return err
		}
		started = append(started, held)
	}
	return nil
}
