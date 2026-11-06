package seat

import (
	"slices"
	"time"

	"agentkit/internal/notify"
	"agentkit/internal/plan"
	"agentkit/internal/run"
)

// doneAsking is what a seat refused its question is told (stop.DONE_ASKING).
const doneAsking = "Your plan is done: every line is proven, and the owner has written nothing since, " +
	"so a question would hold only their attention. Say it in your last message " +
	"instead; they read it when they come back."

// QuestionRefused is why the seat's question goes nowhere, "" where it may ask
// (stop.question_refused): its plan is done, the owner has written nothing in its conversation
// since the plan's last write, and no run of its own is parked undecided, which the owner may be
// asked about.  The error is a read Go cannot make.
func QuestionRefused(name string) (string, error) {
	done, err := plan.DoneAt(name)
	if err != nil || done.IsZero() {
		return "", err
	}
	said, err := notify.OwnerSaid(name)
	if err != nil {
		return "", err
	}
	if slices.ContainsFunc(said, func(at float64) bool { return at > seconds(done) }) {
		return "", nil
	}
	records, err := run.Records()
	if err != nil {
		return "", err
	}
	if parked, err := run.Parked(name, records, time.Now()); parked || err != nil {
		return "", err
	}
	return doneAsking, nil
}
