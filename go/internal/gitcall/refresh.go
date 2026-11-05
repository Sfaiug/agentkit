package gitcall

import (
	"fmt"
	"strings"
)

// Refresh fetches a project's branches and names its default branch before its rules
// are read, both when opening a seat and in the tick's project rules row.
func Refresh(repo string) error {
	g := Git{Repo: repo, Env: ProjectEnv(repo)}
	args := []string{"--quiet", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*"}
	code, said, err := g.Fetch(args...)
	if err == nil && code != 0 {
		err = fmt.Errorf("git fetch %s failed in %s: %s", strings.Join(args, " "), repo, said)
	}
	if err == nil {
		_, err = g.Must("remote", "set-head", "origin", "--auto")
	}
	return err
}
