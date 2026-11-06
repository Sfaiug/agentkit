package run

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
)

// Why is the reason a stop by hand records.
const Why = "stopped by the user"

// settled are what Python's stop.end takes off a record it stops: the waits and retries a final
// state never meets.
var settled = []string{"recovery_pending", "recovery_notified", "recovery_acknowledged_at",
	"lease_wait", "handback_pending", "handback_wait_reason", "handback_note",
	"notification_pending", "pending_inbox", "quota_dry", "refusal_retry",
	"waiting_for", "login_resume_at", "login_back_at", "stall_resume_at",
	"resume_after", "error_retry_at", "error_retries", "waiting_on",
	"waiting_resume_at", "slot_waiting", "launch_pending", "resume_from"}

// holds are what a record names that Python's stop.end does more for than write the record: a
// loop or job to end, a checkout and branch to take, a review to relaunch and follow-ups to
// report.
var holds = []string{"pid", "scope", "job_id", "worktree", "branch", "review_pr",
	"followups", "followup_plan", "followup_runs"}

// Historyless is whether no history.db stands, of which Go writes only a run's own row and its
// tokens yet, and the tick's sync of it: not its steps, checks, waits or reviews, nor the tick's
// other rows.
func Historyless() bool {
	base := filepath.Join(config.Home(), "history.db")
	return absent(base) && absent(base+"-wal")
}

// absent is whether nothing stands at the path, a dangling link being something.
func absent(path string) bool {
	_, err := os.Lstat(path)
	return errors.Is(err, fs.ErrNotExist)
}

// Alone is whether stopping this going run is its record and its report and nothing else, which
// is all Stop carries out: nothing it holds (`holds`, `Lined`), no report to keep a seat's notice
// from, no history row to close, and nothing alive whatever the record says, since a record can
// lag its loop: no user manager that may hold the run's unit (Python stops it by its name) and no
// process carrying the run's marker.
func Alone(dir string, record *Object) bool {
	for _, key := range holds {
		if record.Truthy(key) {
			return false
		}
	}
	return !Ended(record) && !Lined(record) && Historyless() && absent(filepath.Join(dir, "result.md")) &&
		!host.UserManager() && len(host.Marked(dir)) == 0
}

// Stop is Python's stop.end of a run that is Alone, stopped by the user: the record first, under
// its lock, then what an open menu watches, the report and the log.  Its bar is no one's to
// redraw: only a stopped seat's runs come here, and that seat has gone.  A run no longer Alone by
// the time the lock is held is left as it stands, and said so.
func Stop(dir string, now time.Time) error {
	var ended *Object
	err := Change(dir, func(record *Object) error {
		if !Alone(dir, record) {
			return fmt.Errorf("%s moved on while its seat stopped", filepath.Base(dir))
		}
		MarkStopped(record, now, true) // it has no checkout to take
		ended = record
		return nil
	})
	if err != nil {
		return err
	}
	moved := filepath.Join(config.Home(), "state", "runs-moved")
	if file, err := os.OpenFile(moved, os.O_WRONLY|os.O_CREATE, 0o666); err == nil {
		file.Close()
		os.Chtimes(moved, now, now)
	}
	if Report(dir, ended) == nil {
		Note(dir, "ERROR "+Why, now)
	}
	Note(dir, "stopped "+filepath.Base(dir), now)
	return nil
}

// MarkStopped is what Python's stop.end writes on a record a person stopped.
func MarkStopped(record *Object, now time.Time, kept bool) {
	for _, key := range settled {
		record.Delete(key)
	}
	SetAll(record, "state", "stopped", "verdict", "STOPPED", "finished_at", Float(float64(now.UnixNano())/1e9),
		"error", Why, "reported", true, "stop_kept", kept)
}

// Report writes result.md for a run that ended before it had a checkout to report on, under the
// delivery lock: Python's handback.record_result, whose heading such an ending always gets.
func Report(dir string, record *Object) error {
	delivery, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return err
	}
	defer delivery.Close()
	opening := "# FAIL — " + cmp.Or(record.Str("title"), filepath.Base(dir))
	if record.Str("state") == "error" {
		opening = Decision(record, dir, "ERROR", record.Str("error"), "read the result", true)
	}
	result := fmt.Sprintf("%s\n\nVERDICT: %s\n\n## Why this run stopped\n\n%s\n\nrelaunch: %s\n\n",
		opening, cmp.Or(record.Str("verdict"), "none"),
		cmp.Or(record.Str("error"), "no reason was recorded"), Relaunch(dir, record))
	return os.WriteFile(filepath.Join(dir, "result.md"), []byte(result), 0o666)
}

// Relaunch is the command that starts a run's work over: a review's task file, launched alone,
// would build a change of its own titled after the review.
func Relaunch(dir string, record *Object) string {
	if record.Truthy("review_pr") {
		return "ak run --review-pr " + record.Str("review_pr")
	}
	return "ak run " + filepath.Join(dir, "task.md")
}

// Note is one line in the run's log; a log it cannot write costs its writer nothing.
func Note(dir, message string, now time.Time) {
	file, err := os.OpenFile(filepath.Join(dir, "log.txt"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
	if err != nil {
		return
	}
	defer file.Close()
	file.WriteString(now.Format("[15:04:05] ") + message + "\n")
}
