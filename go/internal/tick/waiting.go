package tick

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"
	"regexp"
	"time"

	"agentkit/internal/gitcall"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

func (t *ticking) waitingIdle() bool { return !t.dry || noWaitingResume() }

// A dry row names work without fetching refs or starting a resume.
func noWaitingResume() bool {
	return run.Every(func(dir string, record *run.Object) bool {
		state := record.Str("state")
		if state != "fail" && state != "waiting" {
			return true
		}
		if wait := record.Dict("waiting_on"); wait != nil && wait.Truthy("line") {
			return false
		}
		return record.Truthy("job_id") || run.TickAdmission(record, time.Now()) == "" ||
			state == "fail" && !run.ParkableConflict(dir, record, time.Now())
	})
}

var fullOID = regexp.MustCompile(`^(?:[0-9a-f]{40}|[0-9a-f]{64})$`)

// A failed fetch or an unresolved ref is no move, as transitions.upstream_sha decides.
func upstreamSHA(wt, ref string) string {
	g := gitcall.Git{Repo: wt}
	if code, _, err := g.Fetch("origin"); err != nil || code != 0 {
		return ""
	}
	code, out, _, err := g.Run("rev-parse", ref+"^{commit}")
	sha := gitcall.Strip(out)
	if err != nil || code != 0 || !fullOID.MatchString(sha) {
		return ""
	}
	return sha
}

// waiting is watch.resume_waiting: park once at a fetched baseline, then ask Go's own
// resume to carry the run on when that upstream moves.
func (t *ticking) waiting() error {
	var failed error
	lines := map[string]bool{}
	carried := run.Every(func(dir string, record *run.Object) bool {
		state, now := record.Str("state"), t.clock()
		if state != "fail" && state != "waiting" {
			return true
		}
		// a landing line's member is its lander's to wake, started once a line, which also
		// retries a wake that never started
		if line := loop.ParkedLine(record); line != "" {
			if !lines[line] {
				lines[line] = true
				loop.StartLine(line, t.log.errOut)
			}
			return true
		}
		if wait := record.Dict("waiting_on"); wait != nil && wait.Truthy("line") {
			return false
		}
		if record.Truthy("job_id") || run.TickAdmission(record, now) == "" || state == "fail" && !run.ParkableConflict(dir, record, now) {
			return true
		}
		change := func(edit func(*run.Object) error) bool {
			failed = run.Change(dir, func(current *run.Object) error {
				if !run.Equal(current, record) || state == "fail" && !run.ParkableConflict(dir, current, now) {
					return errMovedRun
				}
				return edit(current)
			})
			return failed == nil || errors.Is(failed, errMovedRun)
		}
		id := filepath.Base(dir)
		if state == "waiting" && !directory(record.Str("worktree")) {
			reason := fmt.Sprintf("this run's worktree %s is gone; it cannot be resumed where it stopped.", cmp.Or(record.Str("worktree"), "(none)"))
			ok := change(func(current *run.Object) error {
				if directory(current.Str("worktree")) {
					return errMovedRun
				}
				run.SetAll(current, "state", "interrupted", "interrupted_at", epoch(now), "interruption_reason", reason, "recovery_pending", true)
				return nil
			})
			if failed == nil {
				t.log.line("WARN " + id + ": " + reason)
			}
			return ok
		}
		if last, ok := dated(record, "waiting_resume_at"); state == "waiting" && ok && 0 <= epoch(now)-last && epoch(now)-last < 600 {
			return true
		}
		wait := record.Dict("waiting_on")
		if wait != nil && wait.Truthy("repair") {
			return false
		}
		ref := run.ConflictUpstream(record)
		if wait != nil {
			ref = cmp.Or(wait.Str("ref"), ref)
		}
		sha := upstreamSHA(record.Str("worktree"), ref)
		if sha == "" {
			return true
		}
		if state == "fail" || wait == nil || !wait.Truthy("sha") {
			ok := change(func(current *run.Object) error {
				baseline := run.NewObject()
				if state == "waiting" && wait != nil {
					baseline = wait.Copy()
				}
				current.Set("waiting_on", run.SetAll(baseline, "ref", ref, "sha", sha))
				if state == "fail" {
					run.SetAll(current, "state", "waiting", "error", current.Get("merge_note"))
					for _, key := range []string{"recovery_pending", "handback_pending", "handback_wait_reason", "waiting_resume_at"} {
						current.Delete(key)
					}
				}
				return nil
			})
			if failed == nil {
				t.log.line(fmt.Sprintf("parked %s waiting on %s at %s", id, ref, sha[:12]))
			}
			return ok
		}
		if sha == wait.Str("sha") {
			return true
		}
		if !loop.Pickup(dir, record) {
			return false
		}
		code, why, err := launch.ResumeExpected(id, record, nil)
		if errors.Is(err, launch.ErrPython) {
			return false
		}
		if err != nil || code != 0 {
			// Pace only a failed Go attempt, never the Python resume this row hands over.
			if !change(func(current *run.Object) error { current.Set("waiting_resume_at", epoch(now)); return nil }) {
				return false
			}
			t.log.line(fmt.Sprintf("WARN could not resume %s: %s", id, cmp.Or(why, fmt.Sprint(err))))
		} else {
			t.log.line(fmt.Sprintf("resumed %s: %s moved (%s..%s)", id, ref, wait.Str("sha")[:min(12, len(wait.Str("sha")))], sha[:12]))
		}
		return true
	})
	if !carried {
		if errors.Is(failed, errMovedRun) {
			return errLeft
		}
		return cmp.Or(failed, errLeft)
	}
	return nil
}

var errMovedRun = errors.New("the run changed during the tick")
