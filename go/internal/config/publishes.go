package config

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// started is when this process read its code (Python's config.STARTED).
var started = time.Now()

// Publishes is whether this process may write what every seat's bar shows (update.publishes):
// only the live checkout as it is now does, or anything where there is none, a test's sandbox.
func Publishes() bool {
	live, err := filepath.EvalSymlinks(filepath.Join(UserHome(), "agentkit"))
	if err != nil && !os.IsNotExist(err) {
		return false
	}
	return !outdated() && (err != nil || live == Repo())
}

// outdated is whether newer agentkit was put in place since this process read its code
// (notify.installed_at): the stamp install leaves, or this program's own file, as a move of the
// checkout stamps nothing.  A home no install stamped has no install to be older than.
func outdated() bool {
	data, err := os.ReadFile(filepath.Join(Home(), "state", "installed-at"))
	if err != nil {
		return false
	}
	stamp, err := strconv.ParseFloat(strings.TrimSpace(string(data)), 64)
	if err != nil {
		return false
	}
	installed := time.UnixMilli(int64(stamp * 1000))
	if program, err := os.Executable(); err == nil {
		if info, err := os.Stat(program); err == nil && info.ModTime().After(installed) {
			installed = info.ModTime()
		}
	}
	return installed.After(started)
}
