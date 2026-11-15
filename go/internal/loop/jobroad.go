package loop

import (
	"os"
	"path/filepath"

	"agentkit/internal/run"
)

// onRoad is whether the record holds key, one of the roads Go does not drive (pythonRoads), but
// for a job's run in a process its job carries, the job's directory in its environment naming the
// job the record names: that job follows its run to its end, as it follows any run it starts.
func onRoad(record *run.Object, key string) bool {
	if started := os.Getenv("AGENTKIT_JOB_DIR"); key == "job_id" && started != "" && filepath.Base(started) == record.Str("job_id") {
		return false
	}
	return record.Truthy(key)
}
