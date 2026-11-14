package loop

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// ErrPython is a run whose stop is Python's, decided before anything is written.
var ErrPython = errors.New("a stop Python ak makes")

// StopRun is `ak run stop <id>`, Python's cmd_stop and end: the record first, under its lock, so a
// driver that notices its children die finds the stop already there, then the loop and all it
// started, then the checkout unless kept.  A refusal is an error, in Python's words.
func StopRun(id string, keep bool, out io.Writer) error {
	dir := filepath.Join(run.Runs(), id)
	read, err := run.Read(dir)
	if errors.Is(err, run.ErrLoneSurrogate) {
		return ErrPython
	}
	if read == nil {
		return fmt.Errorf("%s: cannot read %s", id, filepath.Join(dir, "run.json"))
	}
	state, err := end(dir, keep, run.Why, func(record *run.Object) error {
		if err := checkStopOwner(record); err != nil {
			return err
		}
		word := record.Str("state")
		switch {
		case word == "stopped" && record.Dict("lease_wait") != nil && !record.Truthy("lease_restarted"):
			return ErrPython // stopped to wait on an older run's change, whose restart it calls off
		case word == "stopped":
			return errStop
		case run.Ended(record) && word != "error":
			return fmt.Errorf("%s is already %s; only unfinished work can be stopped", id, run.Field(record, "state", "None"))
		case !goStops(dir, record):
			return ErrPython
		}
		return nil
	})
	if err != nil && !errors.Is(err, errStop) {
		return err
	}
	fmt.Fprintln(out, stopLine(id, state))
	return nil
}

// end is Go's one stop of the run: judge's yes to its record as it stands under its lock, where a
// judge is given, then the record stopped for why, its result, and the loop and all it started,
// still under that lock, then the checkout unless kept.  It is the record as it was read there.
func end(dir string, keep bool, why string, judge func(*run.Object) error) (*run.Object, error) {
	var state *run.Object
	err := run.ChangeThen(dir, func(record *run.Object) error {
		state = record
		if judge != nil {
			if err := judge(record); err != nil {
				return err
			}
		}
		run.MarkStopped(record, time.Now(), keep || !removable(record), why)
		return nil
	}, func() {
		recordResult(dir, state)
		endProcesses(dir, state)
	})
	if err == nil {
		endStopped(dir, state, keep)
	}
	return state, err
}

// endProcesses is what follows the record of a stop under its lock, as Python's end holds it: the
// loop and all it started, then the history row, which counts what the turn they were cut off in
// spent once nothing writes it, a tick's history sync waiting on the lock till then.
func endProcesses(dir string, state *run.Object) {
	if pid, _ := state.Int("pid"); pid > 0 && pid != os.Getpid() && run.ProcessActive(state) {
		host.EndTree(pid)
	}
	host.EndMarked(dir, io.Discard)
	history.Finish(state, func(line string) { appendLog(dir, stamped(line)) })
	redressStopped(state)
}

// endStopped is what follows a stop's lock, as Python's stop_checkout does: its checkout.
func endStopped(dir string, state *run.Object, keep bool) {
	// the checkout is still there, a live loop or a git that said no, so its branch stays with it
	// and the record says kept, as `--keep` does
	if !keep && !stopCheckout(dir, state, func(line string) { appendLog(dir, stamped(line)) }, false) {
		state.Set("stop_kept", true)
		run.Change(dir, func(current *run.Object) error {
			current.Set("stop_kept", true)
			return nil
		})
	}
	appendLog(dir, stamped("stopped "+filepath.Base(dir)))
}

// stopLine is the one line a stop prints: the `from:` is only offered while its branch stands.
func stopLine(id string, state *run.Object) string {
	branch := state.Str("branch")
	switch {
	case branch == "":
		return "stopped " + id
	case !state.Truthy("stop_kept"):
		return fmt.Sprintf("stopped %s: branch %s removed", id, branch)
	}
	return fmt.Sprintf("stopped %s: branch %s kept; relaunch with from: %s", id, branch, branch)
}

// removable is whether a stop without `--keep` takes the run's checkout and branch, Python's
// checkout_removable.
func removable(record *run.Object) bool {
	return !record.Truthy("scratch") && record.Truthy("repo") && record.Truthy("worktree") &&
		filepath.Clean(record.Str("worktree")) != filepath.Clean(record.Str("repo"))
}

// checkStopOwner refuses a seat a run of another's, Python's check_stop_owner; the owner outside a
// seat may stop anything.
func checkStopOwner(record *run.Object) error {
	caller, _, err := config.CurrentSession()
	if err != nil {
		return err
	}
	owner := record.Str("launched_session")
	if owner == "" {
		owner = record.Str("session")
	}
	if caller == "" || owner == "" {
		return nil
	}
	if owner, _, err = config.ResolveSession(owner); err != nil {
		return err
	}
	if owner != caller {
		return fmt.Errorf("owned by seat %s; a seat stops only its own runs", owner)
	}
	return nil
}

// goStops is whether this stop is the record, the result, the process tree, the history row and
// the checkout, all Go does: no process but a Go driver or waiter of this run alive, nothing of a
// job or a review to tell, no landing line, nothing in history Python records (historyHolds), no
// browser tab to shut, and no unit that may hold it, as Python stops a unit by its name.
func goStops(dir string, record *run.Object) bool {
	for _, key := range []string{"job_id", "review_pr"} {
		if record.Truthy(key) {
			return false
		}
	}
	return unitless(record) && !host.UserManager() && !run.Lined(record) && !historyHolds(filepath.Base(dir), record) && !tabbed(filepath.Base(dir)) &&
		(!run.ProcessActive(record) || driving(record, dir))
}

// driving is whether the process the record names is Go's driver of this run, or its waiter, by
// the words it was started with after its name: a program that cannot say is taken for Python's.
func driving(record *run.Object, dir string) bool {
	pid, _ := record.Int("pid")
	said, err := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
	args := strings.Split(strings.TrimRight(string(said), "\x00"), "\x00")
	return err == nil && slices.Equal(args[1:], []string{"run", DriveFlag, dir})
}

// tabbed is whether a browser tab records that run as its opener: Python's to close.
func tabbed(id string) bool {
	tabs, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "browser-tabs.json"))
	if tabs == nil {
		return false
	}
	for _, key := range tabs.Keys() {
		if tab, _ := tabs.Get(key).(*run.Object); tab != nil && tab.Dict("opener") != nil && tab.Dict("opener").Str("run") == id {
			return true
		}
	}
	return false
}
