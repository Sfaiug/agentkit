package loop

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// pythonRoads are what a record holds on a road Go does not drive: Python's to resume.
var pythonRoads = []string{"job_id", "review_pr", "from_pass", "waiting_on", "pickup",
	"resume_after", "lease_wait", "waiting_for"}

// Pickup is whether Go carries that dead run on from where it was cut off: at the review, at the
// executor or the fixer, at the checks after their answer, or at the next round's start.  Decided
// before anything is written, as Python's resume takes any other point.
func Pickup(dir string, record *run.Object) bool {
	switch record.Str("state") {
	case "waiting":
		return waitingPickup(dir, record)
	case "exhausted":
		return exhaustedPickup(dir, record)
	case "running", "interrupted", "error":
		return record.Truthy("no_merge") && cutOff(dir, record) && pairReady(dir, record)
	}
	return false
}

// cutOff is whether the record holds what the loop takes the run up from, at a point it goes on from.
func cutOff(dir string, record *run.Object) bool {
	for _, key := range pythonRoads {
		if record.Truthy(key) {
			return false
		}
	}
	if run.Lined(record) || record.Str("verdict") == "PASS" || !unitless(record) ||
		!record.Truthy("executor") || !record.Truthy("reviewer") || !record.Has("round_summaries") || !isDir(record.Str("worktree")) {
		return false
	}
	if !record.Truthy("scratch") {
		for _, key := range []string{"repo", "branch", "base", "base_sha"} {
			if !record.Truthy(key) {
				return false
			}
		}
	}
	return point(dir, record)
}

// Woken is whether the run waits in its landing line on a verdict its lander wrote, which Go
// carries on into its landing: one it holds no verdict for is the lander's, as Python's resume
// refuses it.  A seat's own PR goes on where Go carries its landing (ownLands).  A unit that
// held it is no reason to leave it: its driver parked it there, and the wake goes in a unit of
// its own (place), as Python's launch_resume puts it.
func Woken(record *run.Object) bool {
	wait := record.Dict("waiting_on")
	if !parkedInLine(record) || !wait.Has("land") && !wait.Has("fix") || run.ProcessActive(record) {
		return false
	}
	for _, key := range pythonRoads {
		if key != "waiting_on" && record.Truthy(key) && !(key == "review_pr" && ownLands(record)) {
			return false
		}
	}
	for _, key := range []string{"repo", "branch", "base", "base_sha"} {
		if !record.Truthy(key) {
			return false
		}
	}
	return isDir(record.Str("worktree"))
}

// unitless is whether no systemd unit holds the run: Python's to stop by name, and to read on a
// dead loop's resume whether its memory cap ended it.
func unitless(record *run.Object) bool {
	return !record.Truthy("scope") || record.Str("scope") == "none"
}

// point is whether the run was cut off where Go goes on from, Python's rounds and continuation: a
// retry directory and an answer with no closing are Python's roads, but for the refusal a run
// waits out on a provider's window, which is no answer.
func point(dir string, record *run.Object) bool {
	rounds, known := record.Int("rounds")
	spent := len(record.List("round_summaries"))
	if !known {
		return false
	}
	if pending := record.Dict("review_pending"); pending != nil {
		if pending.Get("record") == false {
			// a landing's review, which spends no round: the resume takes the target in again (landAgain)
			return !pending.Has("handed") && len(pending.List("failed")) == 0
		}
		left, _, err := run.ChangeLeft(record, dir, rounds, 0, time.Now())
		round, numbered := pending.Int("round")
		for _, key := range []string{"record", "reason", "handed", "passed_head_sha"} {
			if pending.Has(key) {
				return false
			}
		}
		return err == nil && numbered && round <= left && pending.Has("summary") && len(pending.List("failed")) == 0 &&
			!retried(filepath.Join(dir, fmt.Sprintf("round-%d", round)))
	}
	if spent >= rounds || spent > 0 && !exists(filepath.Join(filepath.Dir(record.Str("findings_file")), "findings.json")) {
		return false
	}
	round := filepath.Join(dir, fmt.Sprintf("round-%d", spent+1))
	if !isDir(round) {
		return true
	}
	if retried(round) || len(roleDirs(round, func(entry os.DirEntry) bool { return strings.HasPrefix(entry.Name(), "reviewer") })) > 0 {
		return false
	}
	name, _, _ := openWorker(round)
	refused := run.ExhaustedWait(record) == "window"
	return name != "" && (refused || !exists(filepath.Join(latestTurn(round, name), "final.md"))) || answered(round) != ""
}

// retried is whether Python's retries wrote in that round, which Go does not read on.
func retried(round string) bool {
	found, _ := filepath.Glob(filepath.Join(round, "*-retry*"))
	return len(found) > 0
}

// pairReady is whether the saved pair goes on as it is, which leaves no pick to make: a model that
// cannot run and a reviewer no longer eligible are for Python's to hand over, and so is a saved
// self-review where a pair that is none is ready.
func pairReady(dir string, record *run.Object) bool {
	rules, room, ok := picking(record)
	return ok && asIs(dir, record, rules, room)
}

// delivery is what the last attempt's ending said, Python's clear_delivery: this one owes its own.
var delivery = []string{"handed_back", "handback_pending", "handback_typed", "handback_note", "handback_wait_reason",
	"notification_pending", "recovery_notified"}

// ErrChanged is a run that moved while its resume was being chosen.
var ErrChanged = errors.New("the run changed while choosing recovery; select it again")

// Reopen takes the dead run the record read describes back into the queue for a new driver,
// Python's reap and resume_run: what its last loop left running ended and the death recorded.
// order, where the tick gave one, goes on the record first, in the same write.
func Reopen(dir string, read *run.Object, order func(*run.Object)) error {
	return run.Change(dir, func(record *run.Object) error {
		if !run.Equal(record, read) {
			return ErrChanged
		}
		if order != nil {
			order(record)
		}
		if record.Str("state") == "waiting" && !parkedInLine(record) {
			if err := resumeWaiting(dir, record); err != nil {
				return err
			}
		}
		host.EndMarked(dir, io.Discard)
		// what the resume takes the run up from, Python's resume_from: a dead driver's is an
		// interruption, but for one whose resume the tick ordered, holding the death it noticed
		from := record.Str("state")
		if from == "running" && !run.ResumeOrdered(record, clock()) {
			from = "interrupted"
			reason := "Run process exited or its identity changed."
			run.SetAll(record, "interrupted_at", clock(), "interruption_reason", reason)
			deaths := record.List("deaths")
			var last *run.Object
			if len(deaths) > 0 {
				last, _ = deaths[len(deaths)-1].(*run.Object)
			}
			// once: the tick that noticed it may have recorded it already
			if last == nil || last.Truthy("resumed_at") || !run.Equal(last.Get("pid"), record.Get("pid")) {
				record.Set("deaths", append(append([]any{}, deaths...), run.Fields("at", clock(), "pid", record.Get("pid"), "reason", reason)))
			}
		}
		for _, key := range delivery {
			record.Delete(key)
		}
		if from == "waiting" {
			// what the last attempt said did not deliver is what this one does again
			if pending := record.Dict("review_pending"); pending == nil || pending.Get("record") != false {
				record.Delete("review_pending")
			}
			run.SetAll(record, "merge_failed", false, "merge_note", nil)
		}
		for _, key := range []string{"waiting_resume_at", "slot_waited", "slot_wait_reason", "slot_wait_kind", "stall_resume_at"} {
			record.Delete(key)
		}
		run.SetAll(record, "resume_from", from, "state", "queued", "slot_waiting", true, "queued_at", clock(),
			"pid", os.Getpid(), "process_identity", Identity(os.Getpid()), "recovery_pending", true,
			"recovery_acknowledged_at", nil, "error", nil, "finished_at", nil, "reported", false)
		return nil
	})
}

// takeUp reads back what the loop that died held, Python's Loop on a resume: `rnd` is the rounds
// already spent, which is where a resumed loop counts from.
func (l *loop) takeUp(record *run.Object) {
	l.budget, _ = record.Int("rounds")
	l.rnd = len(record.List("round_summaries"))
	l.execSession, l.reviewSession = record.Str("exec_session"), record.Str("review_session")
	l.findingsFile, l.findings = record.Str("findings_file"), record.Str("findings")
	// the record keeps a tail of the review, the round directory the answer a fixer must work through
	if whole, err := os.ReadFile(l.findingsFile); err == nil {
		l.findings = string(whole)
	}
}

// sayResuming is the log's line of where the run goes on.
func (l *loop) sayResuming(branch string) {
	line := fmt.Sprintf("resuming at round %d/%d: %s", l.rnd+1, l.budget, l.workspace)
	if branch != "" {
		line += " on " + branch
	}
	l.say(line)
}

func (r *repoPlace) reopen(l *loop, _ *run.Object) error {
	r.noWorktree = filepath.Clean(r.wt) == filepath.Clean(r.repo)
	if err := gitcall.NoAutoGC(r.wt); err != nil {
		return err
	}
	l.workspace, l.usersAt = r.wt, r.upstream()
	l.sayResuming(r.branch)
	return r.settle(l)
}

// resumeReview finishes the review the run was cut off in, Python's resume_review: whether it
// passed, false with none pending.  What came before it ran in another process, so its checks run
// again and their failure is recorded, never compared.
func (l *loop) resumeReview() (bool, error) {
	pending, err := l.pendingRound()
	if pending == nil {
		return false, err
	}
	ok, text, err := l.verify()
	if err != nil {
		return false, err
	}
	return l.reviewPending(pending, ok, text)
}

// pendingRound is the review left pending, its round the one under way; nil with none.
func (l *loop) pendingRound() (*run.Object, error) {
	record, err := run.Read(l.dir)
	if record == nil || record.Dict("review_pending") == nil {
		return nil, err
	}
	pending := record.Dict("review_pending")
	l.rnd, _ = pending.Int("round")
	return pending, os.MkdirAll(l.roundDir(), 0o777)
}

// reviewPending is the pending review on checks run for it, Python's resume_review on verified
// ones: whether it passed.
func (l *loop) reviewPending(pending *run.Object, ok bool, text string) (bool, error) {
	if err := l.sameFailure(ok, text, false); err != nil {
		return false, err
	}
	if err := l.place.beforeReview(l); err != nil {
		return false, err
	}
	return l.review(pending.Str("summary"), ok, text, cmp.Or(pending.Str("reason"), "Resume the unfinished review."))
}
