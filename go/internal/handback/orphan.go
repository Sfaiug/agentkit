package handback

import (
	"fmt"
	"os"
	"strings"

	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// Orphaned is whether that ending is one Go reports to the owner in its seat's stead, Python's
// announce for a seat nothing is left of (seat.Unheld): an ending the seat would decide, of no job
// or review, its notices going where this process sends them (handback.speaking_for).  A delivered
// one, which may be recorded or ride a prompt, and one of any other seat not up, which Python
// wakes, reopens or waits for, are Python's.
func Orphaned(record *run.Object) bool {
	state := record.Str("state")
	return run.Seat(record) != "" && run.Ended(record) && !record.Truthy("merged") && state != "not_needed" && state != "stopped" &&
		!record.Truthy("job_id") && !record.Truthy("review_pr") &&
		(!record.Truthy("notify_sink") || run.Equal(record.Get("notify_sink"), os.Getenv("AK_NOTIFY_SINK"))) && seat.Unheld(run.Seat(record))
}

// orphan is the rest of Python's announce for an Orphaned ending, under its delivery lock: the
// owner is asked to continue its task on the gone seat's card, and the ending is reported once
// that card is accepted.  One Go does not card is left to Python, nothing written for it.
func orphan(dir string, said *run.Object, session, id string, say func(string)) {
	verdict := "FAIL"
	if strings.HasPrefix(run.Delivery(said, run.Models()), "PASS") {
		verdict = "PASS"
	}
	task := any(id)
	for _, key := range []string{"run_id", "title"} {
		if said.Truthy(key) {
			task = said.Get(key)
		}
	}
	line := fmt.Sprintf("Its orchestrator session %s is gone. Run finished: %s. Press n in the menu, then say: continue %s.",
		session, verdict, run.Text(task))
	event := "orphan:" + id + ":" + run.Text(said.Get("started_at")) + ":" + run.Text(said.Get("finished_at"))
	code, decided := notify.Orphan(session, line, event, seat.CardWord, func() error {
		// the seat is gone, so a hand-back left pending for it is over
		if !mark(dir, said, "handback_pending", nil, "handback_wait_reason", nil) {
			return errMoved
		}
		say("the orchestrator session " + session + " this run was launched from is gone; asking the user to continue the task")
		if !mark(dir, said, "notification_pending", true) {
			return errMoved
		}
		return nil
	}, os.Stdout, os.Stderr)
	switch {
	case !decided:
	case code == 0:
		mark(dir, said, "reported", true, "notification_pending", nil)
	default:
		say("WARN orphan notification was not accepted; retry required")
	}
}
