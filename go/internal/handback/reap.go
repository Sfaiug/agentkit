package handback

import (
	"context"
	"errors"
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

var errUnstamped = errors.New("the sweep's stamp was not written")

// Reap is Python's reap of the Reapable runs at dirs, each record as it leaves it: what each dead
// loop left behind ended, once per loop, and its record stamped with the loop it swept for
// (`tree_stopped`), onto the record as it stands.  Every run is held under its recovery lock and
// read again, and then the caller's last decision made, which may write once it has decided,
// before any is swept: where one has moved on (errMoved) or decide refuses, nothing is written.
// A stamp that cannot be written is an error too, which Python raises.
func Reap(dirs []string, decide func() error) ([]*run.Object, error) {
	records := make([]*run.Object, len(dirs))
	for i, dir := range dirs {
		release, err := run.Hold(dir)
		if err != nil {
			return nil, err
		}
		defer release()
		if records[i], _ = run.Read(dir); records[i] == nil || !Reapable(records[i]) {
			return nil, errMoved
		}
	}
	if err := decide(); err != nil {
		return nil, err
	}
	for i, dir := range dirs {
		if err := sweep(dir, records[i]); err != nil {
			return nil, err
		}
	}
	return records, nil
}

// sweep ends what the run's dead loop left behind, then stamps the record with that loop under
// the delivery lock, unless that loop is swept already.
func sweep(dir string, record *run.Object) error {
	if swept(record) {
		return nil
	}
	if id := record.Str("run_id"); id != "" {
		host.EndMarked(filepath.Join(run.Runs(), id), io.Discard)
	}
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return err
	}
	defer held.Close()
	if !mark(dir, record, "tree_stopped", loop(record)) {
		return errUnstamped
	}
	return nil
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
