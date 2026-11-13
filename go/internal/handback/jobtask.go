package handback

import (
	"os"
	"path/filepath"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// muted is whether that ending is a job's task's in a process its job started, its seat neither up
// nor asleep: Python's announce leaves it to the job's one line (job.job_started), marking it only
// reported, so no tick offers it again.  The job's directory in this process's environment, naming
// the job the record names, is what says its job started it: a `--bg` job's runs inherit it.
func muted(record *run.Object) bool {
	started, session, state := os.Getenv("AGENTKIT_JOB_DIR"), run.Seat(record), record.Str("state")
	return started != "" && record.Truthy("job_id") && filepath.Base(started) == record.Str("job_id") &&
		run.Ended(record) && !record.Truthy("merged") && state != "not_needed" && state != "stopped" &&
		!seat.Watching(session) && !seat.Asleep(session)
}
