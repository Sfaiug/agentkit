package tmux

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"os/user"
	"path/filepath"
)

// Own is ak's own tmux server, never the person's default one (orch.socket_name): the one
// AGENTKIT_TMUX_SOCKET names, else `agentkit` under the account's own home, and under any other
// HOME `agentkit-` and the first 8 hex digits of the sha256 of its resolved ~/.agentkit
// (orch.home_socket), so an ak tried under a scratch HOME never reaches the seats' server.
func Own() string {
	if name := os.Getenv("AGENTKIT_TMUX_SOCKET"); name != "" {
		return name
	}
	home, set := os.LookupEnv("HOME")
	account, err := user.Current() // a uid with no passwd entry has no home of its own
	if !set && err == nil {
		home = account.HomeDir
	}
	if err == nil && resolved(home) == resolved(account.HomeDir) {
		return "agentkit"
	}
	sum := sha256.Sum256([]byte(resolved(filepath.Join(home, ".agentkit"))))
	return "agentkit-" + hex.EncodeToString(sum[:4])
}

// resolved is a path with every link it holds followed, as far as it exists: Python's resolve.
func resolved(path string) string {
	path, _ = filepath.Abs(path)
	if real, err := filepath.EvalSymlinks(path); err == nil {
		return real
	}
	if parent := filepath.Dir(path); parent != path {
		return filepath.Join(resolved(parent), filepath.Base(path))
	}
	return path
}
