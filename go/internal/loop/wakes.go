package loop

import (
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"sync"
	"time"

	"agentkit/internal/helper"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// wakeEvery is the longest a blamed run waits once no run its red waits on holds a place in the
// line, Python's land.WAKE: the runs ahead leave on their own time, and one check holds a pass for
// hours.
const wakeEvery = 10 * time.Second

// given tells the pass's wake of a red just published.
var given = make(chan struct{}, 1)

func redGiven() {
	select {
	case given <- struct{}{}:
	default: // one telling is waiting already
	}
}

// waking starts the pass's wake, Python's _waking, and returns its end: each run parked in the
// line as it stands on a red Go's woken run carries, waiting on no run with a place in the line
// (redBehind), is woken once a pass: on a host with suite helpers, none is.  It wakes as the pass starts, after each red the pass gives,
// every wakeEvery while it runs, and as it ends.
func waking(line string, said io.Writer) (end func()) {
	done, ended := make(chan struct{}), make(chan struct{})
	go func() {
		defer close(ended)
		woken := map[string]bool{}
		for {
			wakeReds(line, woken, said)
			select {
			case <-done:
				wakeReds(line, woken, said)
				return
			case <-given:
			case <-time.After(wakeEvery):
			}
		}
	}()
	return func() { close(done); <-ended }
}

func wakeReds(line string, woken map[string]bool, said io.Writer) {
	members := lineMembers(line)
	for _, m := range members {
		wait, id := m.record.Dict("waiting_on"), filepath.Base(m.dir)
		if woken[id] || m.record.Str("state") != "waiting" || !wait.Has("fix") || helper.May() ||
			pythons(m.record) || redBehind(wait, members) || run.ProcessActive(m.record) {
			continue
		}
		// Tried, never waited on: a lock held may be a run's that started since the line was read,
		// and the next wake asks again.  Its file lock, not run.Hold: the pass may hold this run's
		// lock through Hold meanwhile, which a Hold or Change here would take as already its own.
		held, err := lock.Try(filepath.Join(m.dir, run.RecoveryLock))
		if errors.Is(err, lock.ErrHeld) {
			continue
		}
		if err == nil {
			if current, _ := run.Read(m.dir); run.Equal(current, m.record) && !run.ProcessActive(current) {
				woken[id] = true // a resume takes its record a moment after it starts
				err = resume(m.dir, current)
			}
			held.Close()
		}
		if err != nil {
			fmt.Fprintf(said, "WARN could not resume %s: %v\n", id, err)
		}
	}
}

// pythons is a member Go's lander leaves to Python's: a target repair's, or a review of a PR other
// than a seat's own.
func pythons(record *run.Object) bool {
	return record.Truthy("review_pr") && !record.Truthy("own_pr") || record.Truthy("repair")
}

// A sharedOut is one writer the pass and its wake both write to.
type sharedOut struct {
	sync.Mutex
	out io.Writer
}

func (w *sharedOut) Write(data []byte) (int, error) {
	w.Lock()
	defer w.Unlock()
	return w.out.Write(data)
}
