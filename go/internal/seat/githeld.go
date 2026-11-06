package seat

import (
	"context"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"agentkit/internal/config"
)

// gitHeld is how long git's answer about a checkout answers every ask in this process
// (orch.git_dirs, open_runs.CEILING): an open screen reads again every few seconds, and one ask
// per read per worktree was 80 processes in 170 s on a host.  Nothing invalidates it, so a wrong
// answer lasts this long at most; a worktree added meanwhile is a path not yet asked.
const gitHeld = time.Minute

var gitAnswers = struct {
	sync.Mutex
	by map[string]heldDirs // by the checkout's resolved path: one question however it is spelled
}{by: map[string]heldDirs{}}

type heldDirs struct {
	until time.Time
	dirs  gitDirs
}

// askedDirs is askDirs's answer for the checkout at path, held for gitHeld.
func askedDirs(path string) gitDirs {
	key := config.Resolve(path)
	gitAnswers.Lock()
	defer gitAnswers.Unlock()
	now := time.Now()
	if held, ok := gitAnswers.by[key]; ok && now.Before(held.until) {
		return held.dirs
	}
	// on a screen open for days, a checkout long gone
	maps.DeleteFunc(gitAnswers.by, func(_ string, held heldDirs) bool { return !now.Before(held.until) })
	dirs := askDirs(path)
	gitAnswers.by[key] = heldDirs{now.Add(gitHeld), dirs}
	return dirs
}

// askDirs is what git says of the checkout at path, in one question; a path holding a newline is
// asked one flag at a time.
func askDirs(path string) gitDirs {
	lines, ok := askGit(path, "--git-dir", "--git-common-dir")
	if ok && len(lines) != 2 {
		gitdir, known := askGit(path, "--git-dir")
		common, same := askGit(path, "--git-common-dir")
		lines, ok = []string{strings.Join(gitdir, "\n"), strings.Join(common, "\n")}, known && same
	}
	if !ok {
		return gitDirs{}
	}
	gitdir, common := config.Resolve(lines[0]), config.Resolve(lines[1])
	return gitDirs{common, gitdir != common, true}
}

// askGit is the lines of the paths git names for those flags, asked at `path` alone, never above
// it, with nothing of git's own environment: an inherited repository would answer for another
// checkout.
func askGit(path string, flags ...string) ([]string, bool) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", append([]string{"rev-parse", "--path-format=absolute"}, flags...)...)
	cmd.Dir = path
	for _, each := range os.Environ() {
		if !strings.HasPrefix(each, "GIT_") {
			cmd.Env = append(cmd.Env, each)
		}
	}
	cmd.Env = append(cmd.Env, "GIT_CEILING_DIRECTORIES="+filepath.Dir(path))
	out, err := cmd.Output()
	if err != nil {
		return nil, false
	}
	return strings.Split(strings.TrimSuffix(string(out), "\n"), "\n"), true
}
