package launch

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/task"
	"agentkit/internal/usage"
)

func resume(id string, bg bool, expected *run.Object, order func(*run.Object), noted func(), out, errOut io.Writer) (int, string, error) {
	took, code, why, err := take(id, expected, order, false)
	if took == nil {
		return code, why, err
	}
	return took.carry(order, noted, bg, out, errOut)
}

// A taken is a resume Go carries out: the run's directory and its record as read and as the
// resume's order leaves it.
type taken struct {
	dir          string
	read, record *run.Object
}

// take is whether Go's resume takes the run up, decided before anything is written: nil with its
// refusal, or ErrPython where the resume is Python's.  live is a loop the caller ends once it is
// taken, which refuses nothing.
func take(id string, expected *run.Object, order func(*run.Object), live bool) (*taken, int, string, error) {
	dir := filepath.Join(run.Runs(), id)
	record, _ := run.Read(dir)
	if expected != nil && !run.Equal(record, expected) {
		return nil, 2, loop.ErrChanged.Error(), nil
	}
	if !reached(dir, record) {
		return nil, 0, "", ErrPython
	}
	read := record
	if order != nil {
		// decided on the record as the order leaves it, which lands only with the resume's own write
		record = read.Copy()
		order(record)
	}
	switch state := record.Str("state"); {
	case !live && run.Active(record) && run.ProcessActive(record):
		return nil, 2, fmt.Sprintf("%s is still running as pid %s", id, run.Field(record, "pid", "None")), nil
	case state == "blocked":
		return nil, 2, "blocked runs are not resumed; the orchestrator writes a new task", nil
	case state == "stopped":
		return nil, 2, "stopped runs are not resumed; start a new task from its branch", nil
	}
	if !goesOn(dir, read, record) {
		return nil, 0, "", ErrPython
	}
	return &taken{dir, read, record}, 0, "", nil
}

// carry carries the taken resume out, order landing with its write.
func (took taken) carry(order func(*run.Object), noted func(), bg bool, out, errOut io.Writer) (int, string, error) {
	dir, read, record := took.dir, took.read, took.record
	id := filepath.Base(dir)
	if dry := loop.Dry(record); dry != "" {
		return parkDry(dir, read, order, dry, out)
	}
	if loop.Logging(dir) {
		// a lander's wake writes into the run's log already: following it would feed it back in
		bg, out = true, io.Discard
	}
	// a receipt still unstarted may have no log yet, which its driver starts; any other run has one
	var offset int64
	if info, err := os.Stat(filepath.Join(dir, "log.txt")); err == nil {
		offset = info.Size()
	} else if !errors.Is(err, fs.ErrNotExist) || !loop.Unstarted(record) {
		return 0, "", err
	}
	// the record and the driver under one hold of the slots, as Python's admission changes under it
	slots, err := holdSlots()
	if err != nil {
		return 0, "", err
	}
	err = loop.Reopen(dir, read, order)
	if err == nil {
		if noted != nil {
			noted()
		}
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
	return loop.Follow(dir, offset, out, errOut), "", nil
}

// reached is whether Go's resume reads that run at all: anything else is Python's before a refusal.
func reached(dir string, record *run.Object) bool {
	return record != nil && gateHere(record) && !ungated(filepath.Base(dir)) &&
		!(run.Lined(record) && !loop.Woken(record)) && run.Carries(record)
}

// goesOn is whether Go's resume takes up a run it reached and did not refuse, record being the
// one read as the resume's order leaves it.  The box comes first, as Python's resume checks it
// before it reads the run's task.
func goesOn(dir string, read, record *run.Object) bool {
	if box.Check() != nil {
		return false
	}
	if _, _, err := task.Read(filepath.Join(dir, "task.md")); err != nil || config.Check() != nil {
		return false
	}
	return driverHere() && !(record.Truthy("repo") && machined()) && pollsHere(record) &&
		(loop.Pickup(dir, record) || loop.Woken(record) || loop.Unstarted(record) && launchStands(dir, record) ||
			loop.Raised(dir, read, record))
}

// driverHere is whether a driver can run on this host: in a box, with meters it can read.
func driverHere() bool {
	return box.Supported && usage.Check() == nil
}
