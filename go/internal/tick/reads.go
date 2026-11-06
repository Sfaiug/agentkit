package tick

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

// missing is whether nothing stands at the path, a dangling link being something.
func missing(path string) bool {
	_, err := os.Lstat(path)
	return errors.Is(err, fs.ErrNotExist)
}

func statePath(name string) string { return filepath.Join(config.Home(), "state", name) }

// cardless is whether no seat's card waits to be retired.
func cardless() bool { return len(config.SeatRecords("card")) == 0 }

// noRenting is whether ak may rent no machine and no suite noted one it needs, a note the pass
// takes even so.
func noRenting() bool { return !config.MayRent() && missing(statePath("google-cloud-need")) }

// noLoginsToEnd is whether the pass stops short of logind: only a server install.sh stamped
// with a user manager asks it.
func noLoginsToEnd() bool { return missing(statePath("installed-at")) || !host.UserManager() }
