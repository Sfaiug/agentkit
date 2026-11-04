package tick

import (
	"errors"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Lease scan compares the diffs of going runs cut from a base, never settled changes.
// A collision record from an earlier scan also needs Python to clear or replace it.
func noLeaseScan() bool {
	if !config.Listable(statePath("leases")) {
		return false
	}
	for _, path := range config.Glob(statePath("leases"), "*.json") {
		held, err := run.ReadJSON(path)
		if errors.Is(err, run.ErrLoneSurrogate) || held != nil && len(held.Keys()) > 0 {
			return false
		}
	}
	return run.Every(func(_ string, record *run.Object) bool {
		return !record.Truthy("repo") || !record.Truthy("base_sha") || record.Truthy("no_merge") ||
			record.Truthy("lease_wait") || !run.Going(record, time.Now()) ||
			record.Str("state") == "waiting" ||
			record.Str("state") == "exhausted" || record.Str("state") == "stalled" || record.Str("state") == "waiting_login" ||
			!directory(record.Str("worktree")) || record.Str("worktree") == record.Str("repo")
	})
}

func noLeaseRestart() bool {
	return run.Every(func(_ string, record *run.Object) bool {
		wait := record.Dict("lease_wait")
		if record.Str("state") != "stopped" || wait == nil || record.Truthy("lease_restarted") {
			return true
		}
		on, named := wait.Get("on").(string)
		if !named {
			return true
		}
		holder, err := run.Read(filepath.Join(run.Runs(), on))
		if errors.Is(err, run.ErrLoneSurrogate) || holder == nil {
			return false
		}
		return run.Going(holder, time.Now()) && holder.Str("state") != "waiting_login" && holder.Str("state") != "stalled" && holder.Str("state") != "exhausted"
	})
}
