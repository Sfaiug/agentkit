package tick

import (
	"cmp"
	"errors"
	"fmt"
	"path/filepath"
	"regexp"

	"agentkit/internal/gitcall"
	"agentkit/internal/launch"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

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
// resume to carry the run on when that upstream moves.  A dry tick says what it would do and
// fetches nothing: a fetch moves the very refs it reports on.
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
				if t.dry {
					t.log.line("would start lander for " + line)
				} else {
					loop.StartLine(line, t.log.errOut)
				}
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
			gone := cmp.Or(record.Str("worktree"), "(none)")
			if t.dry {
				t.log.line(fmt.Sprintf("would interrupt %s: waiting on a merge, but its worktree %s is gone", id, gone))
				return true
			}
			reason := fmt.Sprintf("this run's worktree %s is gone; it cannot be resumed where it stopped.", gone)
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
		// a dry tick says what the run waits on, however its next try is paced
		if last, ok := dated(record, "waiting_resume_at"); !t.dry && state == "waiting" && ok && 0 <= epoch(now)-last && epoch(now)-last < 600 {
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
		if t.dry {
			would := fmt.Sprintf("would resume %s after the next merge to %s", id, ref)
			if state == "fail" {
				would = fmt.Sprintf("would park %s waiting on %s", id, ref)
			}
			t.log.line(would)
			return true
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
		code, why, err := launch.ResumeExpected(id, record, nil, nil)
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
