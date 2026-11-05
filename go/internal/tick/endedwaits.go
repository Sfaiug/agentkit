package tick

import (
	"errors"
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/waitfact"
)

// endedWaits is watch.wait_over: each seat's `ak wait` not yet told has its fact read once a tick,
// written on the wait as `over` the moment it is seen.  A seat gone without the owner closing it is
// then reopened through the revival's reopen and typed that wait's line, once; one the owner closed
// or stopped, or one out of usage, stays down.  Under the lifecycle lock, as the revival is, so an
// owner's close cannot land between the decision and the reopen.  A wait on a pull request, a live
// seat's line at its prompt and the ending a seat's own run hands back are Python's.
func (t *ticking) endedWaits() error {
	return locked(func() error {
		home, known := seat.Looking(t.clock())
		if !known {
			return errLeft
		}
		waits, known := home.Waits()
		if !known {
			return errLeft
		}
		for _, each := range waits {
			if err := t.endWait(each); err != nil {
				return err
			}
		}
		return nil
	})
}

func (t *ticking) endWait(each seat.Revival) error {
	wait := each.File.Dict("wait")
	if wait.Str("kind") != "run" {
		return errLeft
	}
	if !wait.Truthy("over") {
		over, line, ended, err := waitfact.Run(wait.Str("on"), t.clock())
		if err == nil && !over {
			// a stray wait no longer holds a seat whose own work is done (24 Oct)
			line, err = waitfact.WorkLive(each.Name)
			over = line != ""
		}
		if err != nil || !over && wait.Truthy("unread") {
			return errLeft
		}
		if !over {
			return nil
		}
		var reached any
		if ended != "" {
			reached = ended
		}
		if wait, err = seat.MarkWait(each.Name, wait, "over", line, "run", reached); err != nil || wait == nil || wait.Truthy("told") {
			return err
		}
	}
	if ran := wait.Str("run"); ran != "" {
		record, err := run.Read(filepath.Join(run.Runs(), ran))
		if errors.Is(err, run.ErrLoneSurrogate) || record != nil && run.Seat(record) == each.Name {
			return errLeft // its own run hands this ending back, and that is the one line it hears
		}
	}
	file := each.File
	if each.Live {
		return errLeft
	}
	if file.Truthy("stopped_at") || file.Truthy("closed_by_owner") || file.Truthy("usage_wait") {
		return nil
	}
	done, err := waitfact.WorkLive(each.Name)
	if err != nil || done == "" && !each.CanOpen {
		return errLeft
	}
	if told, err := seat.MarkWait(each.Name, wait, "told", run.Float(epoch(t.clock()))); err != nil || told == nil {
		return err
	}
	over := run.Text(wait.Get("over"))
	if done != "" {
		t.log.line(each.Name + ": told that " + over + ", left closed: its work is done")
		return nil
	}
	// one line, whatever it said over several: a newline typed is a key of its own
	why, err := t.reopen(each, config.Fold(over)+"; your wait is over. Decide the next step.")
	if err != nil || why == "" {
		if err == nil {
			t.log.line(each.Name + ": reopened and told that " + over + "; its wait is over")
		}
		return err
	}
	text := fmt.Sprintf("Its orchestrator session %s is gone and its wait is over: %s. agentkit tried to reopen the seat and could not: %s. Press its number in the menu.", each.Name, over, why)
	return notify.Alert(each.Name, text, "wait:"+each.Name+":"+run.Text(wait.Get("at")), t.log.out)
}
