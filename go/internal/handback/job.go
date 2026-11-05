package handback

import (
	"agentkit/internal/job"
	"agentkit/internal/run"
)

// TellJob is a finished job's line handed to the seat that launched it (job.job_hand_back), as its
// launcher ends it and the tick types one left pending: through Tell, its composer mark kept on the
// receipt, and the receipt marked handed back once the line is in.  Its caller holds the job's
// delivery lock, so whoever takes the line second finds nothing left to say.
func TellJob(dir string, receipt *run.Object, line string, say func(string)) string {
	told := Tell(receipt.Str("seat"), line, receipt.Dict("handback_typed"), func(typed *run.Object) error {
		MarkJob(dir, receipt, "handback_typed", typed)
		return nil
	}, say)
	if told == Sent {
		MarkJob(dir, receipt, "handback_pending", nil, "handback_card", nil, "handback_typed", nil,
			"card_sent", run.Fields("kind", "handback", "at", receipt.Get("finished_at")))
	}
	return told
}

// MarkJob is mark_job_delivery: delivery marks written onto the job's receipt as it stands, and
// nothing else, only while it is still the attempt `snapshot` is of; the snapshot takes them too.
// Its caller holds the job's delivery lock.
func MarkJob(dir string, snapshot *run.Object, pairs ...any) bool {
	current, _ := job.Read(dir)
	if current == nil {
		current = snapshot.Copy()
	} else if !sameAttempt(snapshot, current) {
		return false
	}
	marked(current, pairs)
	marked(snapshot, pairs)
	return job.Save(dir, current) == nil
}
