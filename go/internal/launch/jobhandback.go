package launch

import (
	"context"
	"path/filepath"

	"agentkit/internal/handback"
	"agentkit/internal/job"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// handBackJob is the end of Python's run_job_loop, under the job's delivery lock, as a tick may
// hold a line an earlier pass left pending and only one of them types it: the receipt saved
// finished with the job's line on it, so a wait that sees the ending sees its hand-back on the way,
// then the line typed into the seat that launched it; left for the tick to type at the seat's next
// quiet prompt where it is mid-turn, or asleep where Go wakes none; or, the seat gone, the owner
// carded.  A job no seat launched is said here alone.  False for a card not accepted.
func handBackJob(dir string, receipt *run.Object, name, text string, say func(string)) (bool, error) {
	line := text + ". Result: " + filepath.Join(dir, "log.txt") + ". Decide the next step."
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return false, err
	}
	defer held.Close()
	if !receipt.Truthy("seat") {
		say("no seat launched this job, so nothing is sent; the result is here and in `ak run status`")
		receipt.Set("card_sent", run.Fields("kind", "needs", "at", receipt.Get("finished_at")))
		return true, job.Save(dir, receipt)
	}
	run.SetAll(receipt, "handback_pending", line, "handback_card", text)
	if err := job.Save(dir, receipt); err != nil {
		return false, err
	}
	switch handback.TellJob(dir, receipt, line, say) {
	case handback.Sent:
	case handback.Gone:
		return handback.CardJob(dir, receipt, say), nil
	default:
		say("job " + name + ": its seat is not at its prompt; the tick hands it back")
	}
	return true, nil
}
