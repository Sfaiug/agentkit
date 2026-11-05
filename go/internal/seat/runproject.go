package seat

import (
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// runProject is what the run votes its seat's project to be, as Python's handback.run_project
// reads it: the `project` its launch settled, else the `repo:` its task names, the repository it
// worked in for a relative one and none for none, and with no task to read the repository it works
// on.  False where that falls to its task folder's, which Go does not read.
func runProject(record *run.Object) (string, bool) {
	if record.Has("project") {
		return record.Str("project"), true
	}
	repo := record.Str("repo")
	if meta, err := task.Front(filepath.Join(run.Runs(), record.Str("run_id"), "task.md")); err == nil {
		named := meta["repo"]
		if repo = ""; named != "" && !strings.EqualFold(named, "none") {
			if repo = config.Expand(named); !filepath.IsAbs(repo) {
				return record.Str("repo"), true
			}
		}
	}
	return repo, repo != "" || !record.Truthy("task_file")
}
