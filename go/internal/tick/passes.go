package tick

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/job"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// passes are the passes a dry tick runs, in the order Python's watch.local_passes runs them.
// For now each holds only the reads that tell it has nothing to act on, true when it has none: a
// read Go cannot make, or a file it does not know, answers false. A later milestone puts each
// pass itself in its row.
var passes = []func() bool{
	// merged runs are followed: the runs, and the breaks watch.json keeps
	func() bool { return empty(run.Runs()) && stateless() },
	// the boot resume: a boot watch.json has not seen
	func() bool { return configured() && stateless() },
	// the login resume
	func() bool { return empty(run.Runs()) },
	// the session health: worker tokens, the seats tmux holds, their runs, and the stalls and
	// logins watch.json keeps
	func() bool {
		return configured() && stateless() && empty(filepath.Join(config.Home(), "secrets")) && seat.OnNoServer() && empty(run.Runs())
	},
	// the dead-loop resume
	func() bool { return configured() && empty(run.Runs()) },
	// the dead-job relaunch
	func() bool { return empty(job.Jobs()) },
	// the stall ladder
	func() bool { return configured() && empty(run.Runs()) },
	// the usage read: a dry run reads the cache, which acts on nothing
	func() bool { return true },
	// the exhausted resume: its workers are the seat's own selection, which Go does not read yet
	func() bool { return configured() && os.Getenv("AGENTKIT_SESSION") == "" && empty(run.Runs()) },
	// the error retry
	func() bool { return empty(run.Runs()) },
	// the waiting resume
	func() bool { return empty(run.Runs()) },
	// the notification retry
	func() bool { return empty(filepath.Join(config.Home(), "state", "notification-outbox")) },
}

// configured is whether the config loads; Python's passes that load it warn where it does not.
func configured() bool { return config.Check() == nil }

// stateless is whether no tick has kept watch.json, which Go does not read yet.
func stateless() bool {
	_, err := os.Stat(filepath.Join(config.Home(), "state", "watch.json"))
	return errors.Is(err, fs.ErrNotExist)
}

// empty is whether the folder holds nothing, or is not there.
func empty(dir string) bool {
	entries, err := os.ReadDir(dir)
	return errors.Is(err, fs.ErrNotExist) || err == nil && len(entries) == 0
}
