package tick

import (
	"errors"
	"fmt"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/handback"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/waitfact"
)

// endedWaits is watch.wait_over: each seat's `ak wait` not yet told has its fact read once a tick,
// written on the wait as `over` the moment it is seen.  A seat gone without the owner closing it is
// then reopened through the revival's reopen and typed that wait's line, once; one the owner closed
// or stopped, or one out of usage, stays down.  Under the lifecycle lock, as the revival is, so an
// owner's close cannot land between the decision and the reopen.  A wait on a run of the seat's own
// that its run's own notice told is told with it.  A wait on a pull request, a live seat's line at
// its prompt and the ending a seat's own run still hands back are Python's.
func (t *ticking) endedWaits() error {
	var paged []string
	err := locked(func() error {
		home, known := seat.TickHome(t.clock())
		if !known {
			return errLeft
		}
		waits, known := home.Waits()
		if !known {
			return errLeft
		}
		for _, each := range waits {
			alerted, err := t.endWait(each)
			if err != nil {
				return err
			}
			if alerted {
				paged = append(paged, each.Name)
			}
		}
		return nil
	})
	// the word the health row published before that alert is no longer the seat's: the card
	// transition reads it anew (notify.transition), as each seat nobody is in is published
	for _, name := range paged {
		if err == nil {
			_, err = seat.Health(name, func(seat.Live) bool { return false }, t.log.line, t.dry)
		}
	}
	return err
}

// endWait carries one seat's wait, and says whether its owner was paged that it could not be
// reopened.
func (t *ticking) endWait(each seat.Revival) (bool, error) {
	wait := each.File.Dict("wait")
	if wait.Str("kind") != "run" {
		return false, errLeft
	}
	if !wait.Truthy("over") {
		over, line, ended, err := waitfact.Run(wait.Str("on"), t.clock())
		if err == nil && !over {
			// a stray wait no longer holds a seat whose own work is done (24 Oct)
			line, err = waitfact.WorkLive(each.Name)
			over = line != ""
		}
		if err != nil || !over && wait.Truthy("unread") {
			return false, errLeft
		}
		if !over {
			return false, nil
		}
		var reached any
		if ended != "" {
			reached = ended
		}
		if wait, err = seat.MarkWait(each.Name, wait, "over", line, "run", reached); err != nil || wait == nil || wait.Truthy("told") {
			return false, err
		}
	}
	if ran := wait.Str("run"); ran != "" {
		record, err := run.Read(filepath.Join(run.Runs(), ran))
		if errors.Is(err, run.ErrLoneSurrogate) {
			return false, errLeft
		}
		if record != nil && run.Seat(record) == each.Name {
			switch {
			case !run.Ended(record) || run.OwesEnding(record, t.clock()):
				return false, errLeft // its own run hands this ending back, and that is the one line it hears
			case handback.ToldItsSeat(record):
				if told, err := seat.MarkWait(each.Name, wait, "told", run.Float(epoch(t.clock()))); err != nil || told == nil {
					return false, err
				}
				t.log.line(each.Name + ": its own run's notice told it that " + run.Text(wait.Get("over")) + "; its wait is over")
				return false, nil
			}
		}
	}
	file := each.File
	if each.Live {
		return false, errLeft
	}
	if file.Truthy("stopped_at") || file.Truthy("closed_by_owner") || file.Truthy("usage_wait") {
		return false, nil
	}
	done, err := waitfact.WorkLive(each.Name)
	if err != nil || done == "" && !each.CanOpen {
		return false, errLeft
	}
	if told, err := seat.MarkWait(each.Name, wait, "told", run.Float(epoch(t.clock()))); err != nil || told == nil {
		return false, err
	}
	over := run.Text(wait.Get("over"))
	if done != "" {
		t.log.line(each.Name + ": told that " + over + ", left closed: its work is done")
		return false, nil
	}
	// one line, whatever it said over several: a newline typed is a key of its own
	why, err := t.reopen(each, config.Fold(over)+"; your wait is over. Decide the next step.")
	if err != nil || why == "" {
		if err == nil {
			t.log.line(each.Name + ": reopened and told that " + over + "; its wait is over")
		}
		return false, err
	}
	text := fmt.Sprintf("Its orchestrator session %s is gone and its wait is over: %s. agentkit tried to reopen the seat and could not: %s. Press its number in the menu.", each.Name, over, why)
	return true, notify.Alert(each.Name, text, seat.WaitAlert(each.Name, wait), t.log.out)
}
