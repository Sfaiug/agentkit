package loop

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// pythonRoads are what a record holds on a road Go does not drive: Python's to resume.
var pythonRoads = []string{"launched_session", "session", "job_id", "review_pr", "from_pass", "waiting_on", "pickup",
	"stall_resume_at", "resume_after", "lease_wait", "waiting_for"}

// Pickup is whether Go carries that dead run on from where it was cut off: at the review, at the
// executor or the fixer, or at the next round's start.  Decided before anything is written, as
// Python's resume takes any other point.
func Pickup(dir string, record *run.Object) bool {
	if state := record.Str("state"); state != "running" && state != "interrupted" {
		return false
	}
	for _, key := range pythonRoads {
		if record.Truthy(key) {
			return false
		}
	}
	if run.Lined(record) || !record.Truthy("no_merge") || record.Str("verdict") == "PASS" || !unitless(record) ||
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
	return point(dir, record) && pairReady(record)
}

// unitless is whether no systemd unit holds the run: Python's to stop by name and to read on a resume.
func unitless(record *run.Object) bool {
	return !record.Truthy("scope") || record.Str("scope") == "none"
}

// point is whether the run was cut off where Go goes on from, Python's rounds and continuation: a
// retry directory, an answer with no closing and checks cut off are Python's roads.
func point(dir string, record *run.Object) bool {
	rounds, known := record.Int("rounds")
	spent := len(record.List("round_summaries"))
	if !known {
		return false
	}
	if pending := record.Dict("review_pending"); pending != nil {
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
	return name != "" && !exists(filepath.Join(latestTurn(round, name), "final.md"))
}

// retried is whether Python's retries wrote in that round, which Go does not read on.
func retried(round string) bool {
	found, _ := filepath.Glob(filepath.Join(round, "*-retry*"))
	return len(found) > 0
}

// pairReady is whether the saved pair goes on as it is, which leaves no pick to make: a model that
// cannot run, a reviewer no longer eligible and a saved self-review are for Python's to hand over.
func pairReady(record *run.Object) bool {
	l := &loop{workers: names(record.List("workers")), reviewers: names(record.List("reviewers"))}
	rules, ok := l.rules()
	if !ok {
		return false
	}
	readings, err := usage.Read()
	if err != nil {
		return false
	}
	room := withRoom(readings)
	executor, reviewer := record.Str("executor"), record.Str("reviewer")
	return room.Spent(executor) == "" && !rules.Same(executor, reviewer) && slices.Contains(rules.Order(room, true, io.Discard), reviewer)
}

// delivery is what the last attempt's ending said, Python's clear_delivery: this one owes its own.
var delivery = []string{"handed_back", "handback_pending", "handback_typed", "handback_note", "handback_wait_reason",
	"notification_pending", "recovery_notified"}

// ErrChanged is a run that moved while its resume was being chosen.
var ErrChanged = errors.New("the run changed while choosing recovery; select it again")

// Reopen takes the dead run the record read describes back into the queue for a new driver,
// Python's reap and resume_run: what its last loop left running ended and the death recorded.
func Reopen(dir string, read *run.Object) error {
	return run.Change(dir, func(record *run.Object) error {
		if !run.Equal(record, read) {
			return ErrChanged
		}
		host.EndMarked(dir, io.Discard)
		if record.Str("state") == "running" {
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
		for _, key := range []string{"waiting_resume_at", "slot_waited", "slot_wait_reason", "slot_wait_kind"} {
			record.Delete(key)
		}
		run.SetAll(record, "resume_from", "interrupted", "state", "queued", "slot_waiting", true, "queued_at", clock(),
			"pid", os.Getpid(), "process_identity", identity(os.Getpid()), "recovery_pending", true,
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
	if err := noAutoGC(r.wt); err != nil {
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
	record, err := run.Read(l.dir)
	if record == nil {
		return false, err
	}
	pending := record.Dict("review_pending")
	if pending == nil {
		return false, nil
	}
	l.rnd, _ = pending.Int("round")
	if err := os.MkdirAll(l.roundDir(), 0o777); err != nil {
		return false, err
	}
	ok, text, err := l.verify()
	if err != nil {
		return false, err
	}
	if err := l.sameFailure(ok, text, false); err != nil {
		return false, err
	}
	if err := l.place.beforeReview(l); err != nil {
		return false, err
	}
	return l.review(pending.Str("summary"), ok, text, "Resume the unfinished review.")
}
