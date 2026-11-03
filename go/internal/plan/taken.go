package plan

import (
	"cmp"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// taken is whether a deferred line is a run's (plan.taken): one of the seat's, a follow-up with
// the line's check in the line's project, is on its way with it.  ErrUnread where Python reads the
// line's path, or a run's way on, otherwise than Go can.
func taken(current string, line entry) (bool, error) {
	if !pythonPath(line.Project) {
		return false, ErrUnread
	}
	env, err := environ()
	if err != nil {
		return false, err
	}
	repo, _ := place(line.Project, env)
	if repo == "" {
		return false, nil
	}
	if resolved, err := filepath.EvalSymlinks(repo); err == nil {
		repo = resolved
	}
	check, now := strings.TrimFunc(line.Check, config.Space), time.Now()
	var unread error
	for _, dir := range run.Dirs() {
		other, _ := run.Read(dir)
		if other == nil || other.Get("run_id") == nil || other.Str("repo") != repo || other.Get("repair") != nil ||
			!other.Truthy("followup") || other.Dict("followup") == nil || run.Seat(other) != current ||
			strings.TrimFunc(other.Dict("followup").Str("check"), config.Space) != check {
			continue
		}
		going, err := followupOpen(other, now)
		if going {
			return true, nil
		}
		unread = cmp.Or(unread, err)
	}
	return false, unread
}

// followupOpen is whether that fix run is still on its way (handback.followup_open): running,
// about to, or resuming itself.
func followupOpen(other *run.Object, now time.Time) (bool, error) {
	switch other.Str("state") {
	case "running":
		return true, nil
	case "queued":
		return run.ProcessActive(other) || other.Truthy("slot_waiting"), nil
	case "waiting", "waiting_login", "error", "stopped":
		return run.Going(other, now), nil
	case "interrupted":
		return other.Truthy("deaths") && tickResumes(other), nil
	case "exhausted":
		return false, ErrUnread // its wait is transitions.exhausted_wait's
	case "fail":
		if other.Truthy("merge_note") && !other.Truthy("job_id") {
			return false, ErrUnread // a conflict the tick parks is transitions.parkable_conflict's
		}
	}
	return false, nil
}

// tickResumes is whether the tick carries a dead loop on itself (transitions.tick_resumes): one it
// has not given up on, with its worktree still there.
func tickResumes(other *run.Object) bool {
	deaths := other.List("deaths")
	if len(deaths) > 0 {
		if last, _ := deaths[len(deaths)-1].(*run.Object); last != nil && last.Truthy("parked") {
			return false
		}
	}
	info, err := os.Stat(other.Str("worktree"))
	return other.Truthy("worktree") && err == nil && info.IsDir()
}
