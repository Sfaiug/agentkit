package tick

import (
	"errors"
	"path/filepath"
	"time"

	"agentkit/internal/run"
)

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
