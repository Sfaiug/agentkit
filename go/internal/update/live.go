package update

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
)

// LiveHere is whether ~/agentkit is the checkout at repo: only its own tick acts on the host's
// install, or reads what it owes.
func LiveHere(repo string) bool {
	return config.Resolve(filepath.Join(config.UserHome(), "agentkit")) == repo
}

// LiveReady leaves live checks, including their recovery and hand-backs, to Python at this row.
// A tick from another checkout never acts on the host's install.
func LiveReady(repo string) bool {
	if !LiveHere(repo) {
		return true
	}
	checks, err := os.ReadDir(filepath.Join(config.Home(), "state", "live-checks"))
	return exchange != nil && (errors.Is(err, fs.ErrNotExist) || err == nil && len(checks) == 0)
}

// GoLive is Python's go_live where no tests/live.sh holds a move: fetch silently offline, move
// only when ahead, and retry an install owed until it passes, under the same move lock.  A move
// to an origin/main holding one waits for its check (startLive).
func GoLive(repo string, say func(string)) error {
	if !LiveHere(repo) {
		return nil
	}
	if !LiveReady(repo) {
		return ErrPython
	}
	env, err := config.ChildEnv()
	if err != nil {
		return ErrPython
	}
	env = append(env, pins...)
	checkout := filepath.Join(config.UserHome(), "agentkit")
	finish(checkout)
	g := gitcall.Git{Repo: checkout, Env: pins, Cap: gitCap}
	code, _, err := g.Fetch("--quiet", "origin", "main")
	target := ""
	if err == nil && code == 0 {
		target, err = g.Try("rev-parse", "--verify", "--quiet", "origin/main")
		if err != nil {
			return err
		}
	}
	moved := false
	if target != "" {
		code, _, err := g.Out("merge-base", "--is-ancestor", target, "HEAD")
		moved = err == nil && code == 1
	}
	if moved {
		code, _, err := g.Out("cat-file", "-e", target+":tests/live.sh")
		if err != nil {
			return err
		}
		if code == 0 {
			if err := startLive(checkout, target, env, say); err != nil {
				return err
			}
		}
		moved = code != 0
	}
	pending := filepath.Join(config.Home(), "state", "agentkit-install-pending")
	if !moved && !exists(pending) {
		return nil
	}
	head := target
	if !moved {
		head, _ = g.Try("rev-parse", "HEAD")
		target = ""
	}
	var said bytes.Buffer
	if updateOnce(env, checkout, "watch", &said, target, false) == 0 {
		actual, _ := g.Try("rev-parse", "HEAD")
		if !exists(pending) && actual == head {
			say("agentkit is live at " + short(head))
		}
	} else if said.Len() > 0 {
		say(fmt.Sprintf("WARN agentkit did not go live at %s:", short(head)))
		for _, line := range config.SplitLines(said.String()) {
			say("  " + line)
		}
	}
	return nil
}
