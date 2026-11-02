package tick

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

// missing is whether nothing stands at the path, a dangling link being something.
func missing(path string) bool {
	_, err := os.Lstat(path)
	return errors.Is(err, fs.ErrNotExist)
}

func statePath(name string) string { return filepath.Join(config.Home(), "state", name) }

// historyless is whether no history.db stands to read: Go's standard library holds no SQLite.
func historyless() bool {
	base := filepath.Join(config.Home(), "history.db")
	return missing(base) && missing(base+"-wal")
}

// cardless is whether no seat's card waits to be retired.
func cardless() bool { return len(config.Glob(statePath(""), "card-*.json")) == 0 }

// outageless is whether no outage is kept for the alive pass to forget.
func outageless() bool { return missing(statePath("alive.json")) }

// noRenting is whether ak may rent no machine and no suite noted one it needs, a note the pass
// takes even so.
func noRenting() bool { return !config.MayRent() && missing(statePath("google-cloud-need")) }

// noLoginsToEnd is whether the pass stops short of logind: only a server install.sh stamped
// with a user manager asks it.
func noLoginsToEnd() bool { return missing(statePath("installed-at")) || !host.UserManager() }

// noLeftovers is whether no process of this HOME carries an ak mark or a seat's tag, the ones
// the sweep chooses from. Telling which of them are left over is for the milestone that sweeps.
func noLeftovers() bool {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return true // no /proc, as on a Mac: the sweep finds nothing either
	}
	home := "HOME=" + os.Getenv("HOME")
	for _, entry := range entries {
		data, err := os.ReadFile(filepath.Join("/proc", entry.Name(), "environ"))
		if err != nil {
			continue
		}
		env := strings.Split(string(data), "\x00")
		carries := slices.ContainsFunc(env, func(word string) bool {
			return strings.HasPrefix(word, "AK_OWNER=") || strings.HasPrefix(word, "AK_TMUX_OWNER=")
		})
		if carries && slices.Contains(env, home) {
			return false
		}
	}
	return true
}

// retireRead reads the switch retirement record as Python's retire.read does: nothing there and
// a record that is none cost only a read of the lists, and anything else it cannot read raises.
func retireRead() error {
	_, err := os.ReadFile(statePath("retire.json"))
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	return err
}
