package plan

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
)

const checkLimit = 600 * time.Second // an unfinished check proves nothing

var commitID = regexp.MustCompile(`^[0-9a-f]{7,40}$`)

var dropped = []string{"BASH_ENV", "ENV", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
	"GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"}

// environ is what git and a check run with: nothing inherited routes git to another
// repository or brings back seat variables, and the project's env file comes last, as exec
// keeps a key's last value.
func environ(extra map[string]string) []string {
	var env []string
	for _, pair := range os.Environ() {
		key, _, _ := strings.Cut(pair, "=")
		if !strings.HasPrefix(key, "AGENTKIT_") && !strings.HasPrefix(key, "AK_") && !slices.Contains(dropped, key) {
			env = append(env, pair)
		}
	}
	env = append(env, "GIT_TERMINAL_PROMPT=0")
	for key, value := range extra {
		env = append(env, key+"="+value)
	}
	return env
}

func git(ctx context.Context, env []string, dir string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, time.Minute)
	defer cancel()
	// no hook of the project's and no automatic gc, which can lock its checkouts' HEADs
	cmd := exec.CommandContext(ctx, "git", append([]string{"-C", dir, "-c", "core.hooksPath=/dev/null",
		"-c", "gc.auto=0", "-c", "maintenance.auto=false"}, args...)...)
	cmd.Env = env
	out, err := cmd.Output()
	var failed *exec.ExitError
	if ctx.Err() != nil {
		err = errors.New("git did not finish")
	} else if errors.As(err, &failed) {
		err = errors.New(strings.TrimSpace(string(failed.Stderr)))
	}
	return strings.TrimSpace(string(out)), err
}

// holds is whether the repository at dir holds commit, the root its line recorded, or, given
// a revision, whether that descends from it: a remote changed to another repository brings
// that one's history in beside the old root.
func holds(dir, commit, revision string) bool {
	test := []string{"cat-file", "-e", commit + "^{commit}"}
	if revision != "" {
		test = []string{"merge-base", "--is-ancestor", commit, revision}
	}
	if !commitID.MatchString(commit) {
		return false
	}
	_, err := git(context.Background(), environ(nil), dir, test...)
	return err == nil
}

// place is the checkout a line's project names (`~/code/acme#<root commit>`) and that root,
// while the repository there still holds it: a path moved or reused proves nothing.
func place(project string) (repo, root string) {
	at := strings.LastIndex(project, "#")
	if at < 0 {
		return "", ""
	}
	repo, root = config.Expand(project[:at]), project[at+1:]
	if _, err := os.Stat(filepath.Join(repo, ".git")); err != nil || !filepath.IsAbs(repo) || !holds(repo, root, "") {
		return "", ""
	}
	return repo, root
}

// A branch is a project's default branch as just fetched, what its checks run on.
type branch struct {
	repo, root, sha, commit string // commit is `<sha12> <subject>`, as a tick names it
	env                     []string
}

func defaultBranch(ctx context.Context, repo, root string) (*branch, error) {
	extra, err := config.RepoEnv(repo)
	if err != nil {
		return nil, err
	}
	on := &branch{repo: repo, root: root, env: environ(extra)}
	run := func(args ...string) string {
		if err != nil {
			return ""
		}
		out, failed := git(ctx, on.env, repo, args...)
		if failed != nil {
			err = fmt.Errorf("cannot check %s's default branch: %w", filepath.Base(repo), failed)
		}
		return out
	}
	run("fetch", "-q", "origin")
	run("remote", "set-head", "origin", "--auto")
	base := run("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
	on.sha = run("rev-parse", "--verify", base+"^{commit}")
	on.commit = run("log", "-1", "--format=%h %s", "--abbrev=12", on.sha)
	if err != nil {
		return nil, err
	}
	return on, os.MkdirAll(filepath.Join(config.Home(), "wt"), 0o700)
}

// passes is whether check passes on a clean checkout of the branch made for it alone, so
// nothing one check writes is there for the next, and removed after it.  The checkout sits
// beside runs' checkouts in ~/.agentkit/wt, where ak's history reads a test's fixtures as a run's.
func (on *branch) passes(ctx context.Context, check string) bool {
	tmp, err := os.MkdirTemp(filepath.Join(config.Home(), "wt"), "plan-")
	if err != nil {
		return false
	}
	defer os.RemoveAll(tmp)
	tree := filepath.Join(tmp, "main")
	defer func() {
		if _, err := os.Stat(tree); err == nil {
			// cleanup outlives a stop; a check that put a submodule in leaves one git will not remove
			if _, err := git(context.Background(), on.env, on.repo, "worktree", "remove", "--force", tree); err != nil {
				os.RemoveAll(tree)
				git(context.Background(), on.env, on.repo, "worktree", "prune")
			}
		}
	}()
	if _, err := git(ctx, on.env, on.repo, "worktree", "add", "--detach", tree, on.sha); err != nil {
		return false
	}
	if !holds(tree, on.root, "HEAD") {
		return false
	}
	ctx, cancel := context.WithTimeout(ctx, checkLimit)
	defer cancel()
	cmd := exec.CommandContext(ctx, "bash", "-c", check)
	cmd.Dir, cmd.Env = tree, on.env
	stop := group(cmd)
	if cmd.Start() != nil {
		return false
	}
	err = cmd.Wait()
	stop() // no child outlives the checkout
	return err == nil
}
