package handback

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// Interruptible is whether Python's reap interrupts the record of the run at dir and Go carries it:
// a going run whose loop is gone past all reap waits for (run.GoesOn), and that left nothing to stop
// or that Go cannot read: no process of the run still at work (run.Working, as the dead loops row
// reads it), which reap would stop or race; no unit to ask whether its memory cap ended the loop,
// or to stop; a worktree for the dead loops row to continue into only where reap records the death
// of its own loop there for the tick to carry on, not a restart's; and no wait, whose landing line
// Python's save of the interruption times into history.db and wakes.
func Interruptible(dir string, record *run.Object, now float64) bool {
	info, err := os.Stat(record.Str("worktree"))
	return run.Active(record) && !run.GoesOn(record, now) && !run.Working(dir) && !run.Scoped(record) &&
		(!(err == nil && info.IsDir()) || run.TickResumes(record) && !restartEnded(record)) &&
		record.Get("waiting_on") == nil && !run.Lined(record)
}

// Unannounced is whether that reap tells nobody of the interruption: an Interruptible run whose
// death the tick carries on (notify_recovery), which a look at the run carries as the tick does.
func Unannounced(dir string, record *run.Object, now float64) bool {
	return Interruptible(dir, record, now) && run.TickResumes(record)
}

// Interrupted is the Interruptible record as that reap leaves it (transitions.interrupt), which
// says why its loop ended: a restart of the host, a launcher that never started, or a death, the
// death noted where the tick carries it on.
func Interrupted(record *run.Object, now float64) *run.Object {
	reason := run.LoopGone
	if restartEnded(record) {
		reason = "A restart of the host ended the run's loop."
	} else if record.Str("state") == "queued" {
		reason = "Queued launcher exited before starting work."
	}
	run.SetAll(record, "state", "interrupted", "interrupted_at", now,
		"interruption_reason", reason, "recovery_pending", true)
	run.NoteDeath(record, now, reason)
	return record
}

// Interrupt writes that reap of the run at dir under its recovery lock, read again: the record
// Interrupted.  False, with nothing written, where the run is no longer the Interruptible record read.
func Interrupt(dir string, read *run.Object, now float64) (bool, error) {
	err := run.Change(dir, func(current *run.Object) error {
		if !run.Equal(current, read) || !Interruptible(dir, current, now) {
			return errMoved
		}
		Interrupted(current, now)
		return nil
	})
	if errors.Is(err, errMoved) {
		return false, nil
	}
	return err == nil, err
}

// restartEnded is transitions.restart_ended: whether a restart of the host, not a death of its own,
// ended the loop the record names: its death says so and was not resumed, or with none noted, the
// loop started under another boot than this one.
func restartEnded(record *run.Object) bool {
	if ending := run.LoopDeath(record); ending != nil {
		return ending.Truthy("restart") && !ending.Truthy("resumed_at")
	}
	boot := ""
	if identity := record.Dict("process_identity"); identity != nil {
		boot = identity.Str("boot")
	}
	return boot != "" && host.BootID() != "" && boot != host.BootID()
}

// Reapable is whether Python's reap of the record is a sweep Go carries out and nothing more: one
// Sweepable whose recovery nobody is to be told, as notify_recovery tells nobody of one told
// already or launched from no seat, nor reap of a death the tick carries on.
func Reapable(record *run.Object) bool {
	return (record.Truthy("recovery_notified") || run.Launched(record) == "" || run.Carried(record)) && Sweepable(record)
}

// Sweepable is whether Go carries the sweep Python's reap makes of the record: an interrupted run,
// dated, whose loop is gone and is swept already or leaves the sweep no unit to stop and its
// stamp's write no wait in a landing line to count.
func Sweepable(record *run.Object) bool {
	return record.Str("state") == "interrupted" && record.Truthy("interrupted_at") &&
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
