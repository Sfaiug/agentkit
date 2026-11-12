package seat

import (
	"errors"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

var errHarnessUnread = errors.New("the seat's harness could not be read")

// Hears is how the seat hears news of its own run that it has nothing to decide in, a merge or that
// merge's change going live: typed now where it ends the seat's wait (handback.ends_wait), else
// riding on its next prompt where its harness takes a prompt context (handback.rides), else
// recorded and never typed, as all of it is for a seat owing no work (seat_owes_nothing) and of an
// ordered job's task, which the job's one line says (job.in_order).  An error where Go cannot read
// which as Python does.
func Hears(record *run.Object, census []*run.Object, session string) (now, rides bool, err error) {
	if inOrder(record) || session == "" {
		return false, false, nil
	}
	if owes, err := plan.Owes(session); !owes || err != nil {
		return false, false, err
	}
	own := config.SeatHarness(session)
	if own == "" {
		return false, false, errHarnessUnread
	}
	if now, err = EndsWait(session, census, record); now || err != nil {
		return now, false, err
	}
	return false, harness.TakesContext(own), nil
}
