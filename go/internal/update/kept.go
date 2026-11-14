package update

import (
	"context"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lock"
)

// A move is final only once a tick of the version it put live completes (Final), as Python's
// agentkit/versions.py has it: until then the version it replaced is kept (keptVersion), and
// nothing else moves.

// keepLink is where a move keeps the version it replaced, Python's versions.keep_link: a link to
// its bin/ak, which the cron line runs.  "" on a client, which runs no tick that could make its
// moves final, so keeps nothing, a link a server left it included.
func keepLink() string {
	if server, _ := os.ReadFile(filepath.Join(config.Home(), "state", "server")); strings.TrimFunc(string(server), config.Space) != "" {
		return ""
	}
	return filepath.Join(config.Home(), "tmp", "keep", "ak")
}

// keptVersion is the version the last move replaced, while that move is not final: the folder of
// the bin/ak keepLink names, else "", Python's versions.kept.
func keptVersion() string {
	link := keepLink()
	if link == "" {
		return ""
	}
	named, err := os.Readlink(link)
	if err != nil {
		return ""
	}
	return filepath.Dir(filepath.Dir(named))
}

// holding is the versions hold, Python's versions.holding, until the file it answers closes: the
// versions folder's flock, made where missing.
func holding() (*os.File, error) {
	versions := filepath.Join(config.Home(), "versions")
	if err := os.MkdirAll(versions, 0o777); err != nil {
		return nil, err
	}
	return lock.Wait(context.Background(), versions)
}

// keep exchanges next for live, the version it replaces kept: the link goes in before the
// exchange, which leaves that version at next, so a move cut off right after it is kept too, and
// both under one hold, or a tick of the version replaced completing between them would take it.
func keep(live, next string) error {
	held, err := holding()
	if err != nil {
		return err
	}
	defer held.Close()
	link := keepLink()
	if link != "" {
		os.MkdirAll(filepath.Dir(link), 0o777)
		if err := os.Symlink(filepath.Join(next, "bin", "ak"), link); err != nil {
			return err
		}
	}
	if err = exchange(live, next); err != nil && link != "" {
		os.Remove(link) // nothing was replaced
	}
	return err
}

// Final is a completed tick's end, which began in the folder began is a stat of: one that began in
// the version at ~/agentkit now proves it runs, and makes the move that put it live final.  One
// that began before the move, the move's own among them, ran the version replaced, and proves
// nothing.
func Final(began os.FileInfo) {
	link := keepLink()
	if began == nil || link == "" {
		return
	}
	if _, err := os.Lstat(link); err != nil {
		return
	}
	held, err := holding() // as swap holds it from a move's link to its exchange
	if err != nil {
		return
	}
	defer held.Close()
	if live, err := os.Stat(filepath.Join(config.UserHome(), "agentkit")); err == nil && os.SameFile(began, live) {
		os.Remove(link)
	}
}
