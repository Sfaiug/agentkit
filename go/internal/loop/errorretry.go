package loop

import (
	"path/filepath"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/task"
)

// ParkError is a run that just ended in error, Python's park_error: one the tick may take up and a
// resume could carry on is born with its next retry on its record, anything else keeps none and
// is a person's from the start.  The rung tried before stays, so an error again waits longer.
func ParkError(dir string, record *run.Object, now time.Time) {
	if run.TickAdmission(record, now) != "" && ErrorResumable(dir, record) {
		ScheduleErrorRetry(record, now)
		return
	}
	DropErrorRetry(record)
}

// ScheduleErrorRetry stamps the tick's next retry of an errored run, Python's
// schedule_error_retry: on the rung already tried, a worker turn's transient waits, then hourly.
func ScheduleErrorRetry(record *run.Object, now time.Time) {
	retries := rung(record)
	run.SetAll(record, "error_retries", retries,
		"error_retry_at", float64(now.UnixNano())/1e9+transientDelay(retries+1).Seconds())
}

// ClimbErrorRetry is a due retry taking the next rung before its resume owns the run, so a start
// that fails is tried again a rung up.
func ClimbErrorRetry(record *run.Object, now time.Time) {
	record.Set("error_retries", rung(record)+1)
	ScheduleErrorRetry(record, now)
}

// rung is the retry already tried: 0 where the record holds no count Python reads as one.
func rung(record *run.Object) int {
	retries, ok := record.Int("error_retries")
	if !ok || retries < 0 {
		return 0
	}
	return retries
}

// DropErrorRetry ends an error's retry episode: the rung goes with the hour.
func DropErrorRetry(record *run.Object) {
	record.Delete("error_retry_at")
	record.Delete("error_retries")
}

// ErrorResumable is whether a resume could carry that errored run on, Python's error_resumable,
// asked before anything is scheduled: its worktree still there, the keys a resume replays, and a
// task that still parses with a done-when.  A job's run is its job's to settle, and a review the
// watch relaunches itself; retrying what nobody can run would fail on the hour, saying nothing new.
func ErrorResumable(dir string, record *run.Object) bool {
	if record.Truthy("review_pr") || record.Truthy("job_id") || !isDir(record.Str("worktree")) {
		return false
	}
	keys := []string{"repo", "worktree", "branch", "base", "base_sha", "rounds"}
	if record.Truthy("scratch") {
		keys = []string{"worktree", "rounds"}
	}
	for _, key := range keys {
		if !record.Truthy(key) {
			return false
		}
	}
	_, _, err := task.Read(filepath.Join(dir, "task.md"))
	return err == nil
}
