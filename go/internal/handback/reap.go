package handback

import (
	"context"
	"io"
	"path/filepath"
	"strings"

	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// Reapable is whether Python's reap of the record is a sweep Go carries out and nothing more: an
// interrupted run, dated, whose loop is gone and whose recovery was told, so notify_recovery
// says nothing, and whose loop is swept already or leaves the sweep no unit to stop and its
// stamp's write no wait in a landing line to count.
func Reapable(record *run.Object) bool {
	return record.Str("state") == "interrupted" && record.Truthy("interrupted_at") && record.Truthy("recovery_notified") &&
		!run.ProcessActive(record) && (swept(record) || !run.Lined(record) && !unitStopped(record))
}

// Reap is the record as Python's reap(dir, record) leaves a run whose listing Go keeps: an
// ended run as run.Reap leaves it, or a Reapable one reaped under its recovery lock, what its
// dead loop left behind ended once per loop and the record stamped with the loop it swept for,
// onto the record as it stands.  errMoved where the run is no longer Reapable once locked.
func Reap(dir string, record *run.Object) (*run.Object, error) {
	if !Reapable(record) {
		reaped, _ := run.Reap(record)
		return reaped, nil
	}
	release, err := run.Hold(dir)
	if err != nil {
		return nil, err
	}
	defer release()
	if record, _ = run.Read(dir); record == nil || !Reapable(record) {
		return nil, errMoved
	}
	if swept(record) {
		return record, nil
	}
	if id := record.Str("run_id"); id != "" {
		host.EndMarked(filepath.Join(run.Runs(), id), io.Discard)
	}
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return nil, err
	}
	defer held.Close()
	mark(dir, record, "tree_stopped", loop(record))
	return record, nil
}

// loop is what tells one activation of a run from the next, which a sweep is stamped with.
func loop(record *run.Object) []any {
	return []any{record.Get("pid"), record.Get("process_identity")}
}

func swept(record *run.Object) bool { return run.Equal(record.Get("tree_stopped"), loop(record)) }

// unitStopped is whether Python's sweep asks the user manager to stop the unit the run names
// (orch.stop_scope), which Go has no stop of.
func unitStopped(record *run.Object) bool {
	scope, _ := record.Get("scope").(string)
	return scope != "" && scope != "none" && !strings.HasPrefix(scope, "none (") && host.UserManager()
}
