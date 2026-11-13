package handback

import (
	"os"

	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// CardJob asks the owner what a finished job's line would have told the seat that launched it,
// gone since (run_job_loop): the job's card, under the event of its ending, as Python's
// notify.shaped asks it, the line struck off the receipt once the ask is Go's, and the receipt
// marked carded.  False only for a card not accepted, marked to be retried.  Where Go does not
// card that seat nothing is written, and the line stays pending for the tick to hand on.  Its
// caller holds the job's delivery lock.
func CardJob(dir string, receipt *run.Object, say func(string)) bool {
	card, _ := receipt.Get("handback_card").(string)
	if card == "" {
		card, _ = receipt.Get("handback_pending").(string)
	}
	event := "job:" + run.Text(receipt.Get("job_id")) + ":" + run.Text(receipt.Get("finished_at"))
	taken := false
	code, decided := notify.Orphan(receipt.Str("seat"), card, event, seat.CardWord, func() error {
		if taken = MarkJob(dir, receipt, "handback_pending", nil, "handback_card", nil, "handback_typed", nil); !taken {
			return errMoved
		}
		return nil
	}, os.Stdout, os.Stderr)
	switch {
	case !taken:
		return true
	case decided && code != 0:
		MarkJob(dir, receipt, "card_pending", true)
		say("WARN job card was not accepted; retry required")
		return false
	}
	// a notice standing for its seat's word to card is asked as shaped's is: told
	MarkJob(dir, receipt, "card_sent", run.Fields("kind", "needs", "at", receipt.Get("finished_at")))
	return true
}
