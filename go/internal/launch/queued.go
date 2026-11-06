package launch

import (
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// launchStands is whether the launch a queued receipt saved would start in Go as it stands: its
// task refuses nothing (Refusal), and it and its options, bound to its run's lists or else the
// config's, pass Go's launch preflight outright, in the repository the launch settled.  Anything
// else is Python's, whose resume judges a waiting launch again.
func launchStands(dir string, record *run.Object) bool {
	path := filepath.Join(dir, "task.md")
	meta, cmds, err := task.Read(path)
	data, unread := os.ReadFile(path)
	if err != nil || unread != nil {
		return false
	}
	if why, err := Refusal(path, meta, cmds); why != "" || err != nil {
		return false
	}
	opts := record.Dict("launch_opts")
	values, flags := map[string]string{}, map[string]bool{}
	for _, flag := range run.LaunchValues {
		if value := opts.Str(flag); value != "" {
			values[flag] = value
		}
	}
	for _, flag := range run.LaunchSwitches {
		flags[flag] = opts.Truthy(flag)
	}
	bound := config.Binding{Workers: record.List("workers"), Reviewers: record.List("reviewers")}
	if bound.Workers == nil {
		if bound, err = config.Bind(); err != nil {
			return false
		}
	}
	if len(bound.Workers) == 0 {
		return false
	}
	reason, _, at, err := preflight(meta, cmds, path, path, task.Title(task.Text(data), "task"), values, flags, bound)
	return err == nil && reason == "" && config.Resolve(at.repo) == config.Resolve(record.Str("repo"))
}
