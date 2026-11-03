package launch

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/task"
	"agentkit/internal/usage"
)

// Resume is `ak run resume <id>`, Python's resume_run on a dead run Go can pick up from: its
// refusals in its words, `ak run`'s exit status, and why it refused.  Anything else it leaves to
// Python (ErrPython) before it writes anything.
func Resume(id string, bg bool, out, errOut io.Writer) (int, string, error) {
	dir := filepath.Join(run.Runs(), id)
	record, _ := run.Read(dir)
	if record == nil || elsewhere() || run.Lined(record) {
		return 0, "", ErrPython
	}
	switch state := record.Str("state"); {
	case run.Active(record) && run.ProcessActive(record):
		return 2, fmt.Sprintf("%s is still running as pid %s", id, run.Field(record, "pid", "None")), nil
	case state == "blocked":
		return 2, "blocked runs are not resumed; the orchestrator writes a new task", nil
	case state == "stopped":
		return 2, "stopped runs are not resumed; start a new task from its branch", nil
	}
	_, cmds, err := task.Read(filepath.Join(dir, "task.md"))
	if err != nil || config.Check() != nil || box.Check() != nil {
		return 0, "", ErrPython
	}
	// only a run that does not land is Go's to pick up, so its checks are the task's alone
	every, _ := task.Group(task.RoundCommands(cmds, "", false))
	if !driverHere(every) || record.Truthy("repo") && helped() || !loop.Pickup(dir, record) {
		return 0, "", ErrPython
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
	err = loop.Reopen(dir, record)
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

// driverHere is whether a driver can take these checks on this host: placed, with meters it can read.
func driverHere(every []string) bool {
	return placed(every) && usage.Check() == nil
}

// placed is whether this host can hold a driver for these checks: a box, no user manager to place
// the run under, and no check that names a suite's share.
func placed(every []string) bool {
	return box.Supported && !host.UserManager() &&
		!slices.ContainsFunc(every, func(cmd string) bool { return namesShard.MatchString(cmd) })
}

// helped is whether a helper may take a repository's checks, which Python does and Go does not.
func helped() bool {
	return len(config.MachineNames()) > 0 || config.MayRent()
}
