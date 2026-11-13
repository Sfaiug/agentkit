package cli

import (
	"agentkit/internal/handback"
	"agentkit/internal/run"
)

// lookLeft is whether the caller's own look at the run at dir reads what Go cannot as Python does
// (handback.LookOwed): asked before the command writes or prints anything, it leaves the command
// to Python ak.
func lookLeft(caller, dir string) bool {
	record, _ := run.Read(dir)
	if record == nil || caller == "" || run.Seat(record) != caller {
		return false
	}
	_, err := handback.LookOwed(record)
	return err != nil
}
