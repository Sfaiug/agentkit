package launch

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// Fresh is how a seat's fresh launch Go makes no run of ends, asked as Python's check_seat_queue
// asks it once every check before it passed: a job of several task files, whatever run directory
// it carries, or a run carrying a directory Python resumes nothing for, which it ignores, saying so,
// and launches afresh without asking for a change under way.  Refused where the seat's queue lacks
// room for every task it starts at once, one for an ordered job; ErrPython for any other, which
// Python makes or refuses in its own words: one from no seat or with no executor, a directory
// Python takes up or refuses, a task an earlier check refuses, or a launch the queue lets through.
func Fresh(paths []string, flags map[string]bool, errOut io.Writer) (int, string, error) {
	seat, record, err := queueSeat()
	if seat == "" || err != nil || os.Getenv("HOME") == "" || !readable(paths...) || len(paths) > 1 && flags["--no-worktree"] {
		return 0, "", ErrPython
	}
	if bound, err := config.BindSeat(record); err != nil || len(bound.Workers) == 0 {
		return 0, "", ErrPython
	}
	carried := os.Getenv("AGENTKIT_RUN_DIR")
	if len(paths) == 1 && (Queued() || !readable(carried) || refusedAt(carried)) {
		return 0, "", ErrPython
	}
	names := map[string]bool{}
	for _, path := range paths {
		// a job keys its tasks on their file names
		if names[filepath.Base(path)] || !passes(path, len(paths) > 1 && !flags["--anyway"]) {
			return 0, "", ErrPython
		}
		names[filepath.Base(path)] = true
	}
	asked := len(paths)
	if flags["--in-order"] {
		asked = 1
	}
	why := seatFull(seat, asked)
	if why == "" {
		return 0, "", ErrPython
	}
	if len(paths) == 1 {
		fmt.Fprintf(errOut, "ak run: ignoring AGENTKIT_RUN_DIR=%s: not a queued run\n", carried)
	}
	return 2, why, nil
}

// refusedAt is whether Python refuses a launch carrying that run's directory: one a resume could
// carry on, or one this very process stopped as it waited.  A record it cannot read is none, but
// one Go cannot keep is Python's to read.
func refusedAt(dir string) bool {
	record, err := run.Read(dir)
	if record == nil {
		return errors.Is(err, run.ErrLoneSurrogate)
	}
	pid, _ := record.Int("pid")
	return run.NeedsRecovery(record) || record.Str("state") == "stopped" && pid == os.Getpid()
}

// passes is whether Python asks the task at path nothing it refuses before its seat's queue: its
// `repo:`, its rounds, a change under way where asked, and its project's contract.
func passes(path string, underWay bool) bool {
	data, err := os.ReadFile(path)
	meta, cmds, unread := task.Read(path)
	if err != nil || unread != nil || !utf8.Valid(data) {
		return false
	}
	repo, refused, err := checkout(meta, path, path)
	if err != nil || refused != "" {
		return false
	}
	numbers, err := numbers(repo, false)
	if err != nil || task.RoundsOver(meta["rounds"], "task rounds", numbers.Rounds) != "" {
		return false
	}
	if underWay {
		if found, err := rivals(repo, path, titleOf(path, task.Text(data)), cmds); err != nil || len(found) > 0 {
			return false
		}
	}
	return gitcall.ContractRefusal(repo) == ""
}
