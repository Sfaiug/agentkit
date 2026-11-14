package tick

import (
	"errors"
	"path/filepath"
	"time"

	"agentkit/internal/job"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/waitfact"
)

// waitFact is wait_fact for the waits the tick ends: a job's, or a run's with the run whose ending
// that is.
func waitFact(wait *run.Object, now time.Time) (bool, string, string, error) {
	if wait.Str("kind") == "job" {
		over, line, err := waitfact.Job(wait.Str("on"))
		return over, line, "", err
	}
	return waitfact.Run(wait.Str("on"), now)
}

// ownJob is whether the seat's ended wait is on a job of its own, whose hand-back is the one line
// it hears: none is typed for it, and the wait is told once the hand-back is in, or once the seat
// answered it by resuming the runs it told of, whose own endings then tell it.
func (t *ticking) ownJob(name string, wait *run.Object) (bool, error) {
	if wait.Str("kind") != "job" {
		return false, nil
	}
	receipt, err := job.Read(filepath.Join(job.Jobs(), wait.Str("on")))
	if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
		return false, errLeft
	}
	// by its seat's name now, so a seat renamed since is still its own
	if receipt == nil || run.Seat(run.Fields("launched_session", receipt.Get("seat"))) != name {
		return false, nil
	}
	if receipt.Truthy("handback_pending") {
		return true, nil
	}
	card := receipt.Dict("card_sent")
	if card == nil || card.Str("kind") != "handback" && card.Str("kind") != "resumed" {
		return false, nil
	}
	if told, err := seat.MarkWait(name, wait, "told", run.Float(epoch(t.clock()))); err != nil || told == nil {
		return true, err
	}
	t.log.line(name + ": its own job's notice told it that " + run.Text(wait.Get("over")) + "; its wait is over")
	return true, nil
}
