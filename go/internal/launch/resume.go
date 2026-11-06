package launch

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/helper"
	"agentkit/internal/host"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/task"
	"agentkit/internal/usage"
)

func resume(id string, bg bool, expected *run.Object, order func(*run.Object), out, errOut io.Writer) (int, string, error) {
	dir := filepath.Join(run.Runs(), id)
	record, _ := run.Read(dir)
	if expected != nil && !run.Equal(record, expected) {
		return 2, loop.ErrChanged.Error(), nil
	}
	if !reached(dir, record) {
		return 0, "", ErrPython
	}
	read := record
	if order != nil {
		// decided on the record as the order leaves it, which lands only with the resume's own write
		record = read.Copy()
		order(record)
	}
	switch state := record.Str("state"); {
	case run.Active(record) && run.ProcessActive(record):
		return 2, fmt.Sprintf("%s is still running as pid %s", id, run.Field(record, "pid", "None")), nil
	case state == "blocked":
		return 2, "blocked runs are not resumed; the orchestrator writes a new task", nil
	case state == "stopped":
		return 2, "stopped runs are not resumed; start a new task from its branch", nil
	}
	if !goesOn(dir, record) {
		return 0, "", ErrPython
	}
	if loop.Logging(dir) {
		// a lander's wake writes into the run's log already: following it would feed it back in
		bg, out = true, io.Discard
	}
	log := filepath.Join(dir, "log.txt")
	info, err := os.Stat(log)
	if err != nil {
		return 0, "", err
	}
	// the record and the driver under one hold of the slots, as Python's admission changes under it
	slots, err := holdSlots()
	if err != nil {
		return 0, "", err
	}
	err = loop.Reopen(dir, read, order)
	if err == nil {
		err = loop.Start(dir, out, bg)
	}
	slots.Close()
	switch {
	case errors.Is(err, loop.ErrChanged):
		return 2, err.Error(), nil
	case errors.Is(err, loop.ErrStopped):
		return 2, id + " was stopped before it could start; nothing was launched", nil
	case err != nil:
		return 0, "", err
	}
	if bg {
		return 0, "", nil
	}
	return loop.Follow(dir, info.Size(), out, errOut), "", nil
}

// reached is whether Go's resume reads that run at all: anything else is Python's before a refusal.
func reached(dir string, record *run.Object) bool {
	return record != nil && !elsewhere(filepath.Base(dir)) && !(run.Lined(record) && !loop.Woken(record)) && run.Carries(record)
}

// goesOn is whether Go's resume takes up a run it reached and did not refuse.  The box comes
// first, as Python's resume checks it before it reads the run's task.
func goesOn(dir string, record *run.Object) bool {
	if box.Check() != nil {
		return false
	}
	if _, _, err := task.Read(filepath.Join(dir, "task.md")); err != nil || config.Check() != nil {
		return false
	}
	return driverHere() && !(record.Truthy("repo") && helper.May()) && (loop.Pickup(dir, record) || loop.Woken(record))
}

// driverHere is whether a driver can run on this host: placed, with meters it can read, its turns
// on no provider's accounts.
func driverHere() bool {
	return placed() && usage.Check() == nil && !accountTurns()
}

// placed is whether this host can hold a driver: a box, and no user manager to place the run under.
func placed() bool {
	return box.Supported && !host.UserManager()
}
