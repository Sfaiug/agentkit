package plan

import (
	"cmp"
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
	"agentkit/internal/host"
)

const checkLimit = 600 * time.Second // an unfinished check proves nothing

var commitID = regexp.MustCompile(`^[0-9a-f]{7,40}$`)

var dropped = []string{"BASH_ENV", "ENV", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
	"GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"}

// environ is what git runs with: nothing inherited routes it to another repository or
// brings back seat variables.
func environ() ([]string, error) {
	seat, err := config.SeatEnv()
	if err != nil {
		return nil, err
	}
	var env []string
	for _, pair := range os.Environ() {
		key, _, _ := strings.Cut(pair, "=")
		if !strings.HasPrefix(key, "AGENTKIT_") && !strings.HasPrefix(key, "AK_") &&
			!slices.Contains(dropped, key) && !slices.Contains(seat, key) {
			env = append(env, pair)
		}
	}
	return append(env, "GIT_TERMINAL_PROMPT=0"), nil
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
func holds(env []string, dir, commit, revision string) bool {
	test := []string{"cat-file", "-e", commit + "^{commit}"}
	if revision != "" {
		test = []string{"merge-base", "--is-ancestor", commit, revision}
	}
	if !commitID.MatchString(commit) {
		return false
	}
	_, err := git(context.Background(), env, dir, test...)
	return err == nil
}

// place is the checkout a line's project names (`~/code/acme#<root commit>`) and that root,
// while the repository there still holds it: a path moved or reused proves nothing.
func place(project string, env []string) (repo, root string) {
	at := strings.LastIndex(project, "#")
	if at < 0 {
		return "", ""
	}
	repo, root = config.Expand(project[:at]), project[at+1:]
	if _, err := os.Stat(filepath.Join(repo, ".git")); err != nil || !filepath.IsAbs(repo) || !holds(env, repo, root, "") {
		return "", ""
	}
	return repo, root
}

// pythonPath is whether place reads a project's path as Python's Path does: Go takes each `..`
// away by its name, where the system follows a link before it, and expands no other user's `~`.
func pythonPath(project string) bool {
	if at := strings.LastIndex(project, "#"); at >= 0 {
		project = project[:at]
	}
	names := strings.Split(project, "/")
	return !slices.Contains(names, "..") && (names[0] == "~" || !strings.HasPrefix(names[0], "~"))
}

// A branch is a project's default branch as just fetched, or the commit a line names: what checks run on.
type branch struct {
	repo, root, sha, commit string   // commit is `<sha12> <subject>`, as a tick names it
	clean, env              []string // env adds the project's env file to clean
}

// defaultBranch fetches the project's default branch, or, given at, that commit: the one a
// line's check was proven failing on.  Git there and its checks get the project's env file,
// as a run's checks do: what git does not hold, such as the project's interpreter, it names
// there; which repository a checkout holds is read without it.
func defaultBranch(ctx context.Context, repo, root, at string, clean []string) (*branch, error) {
	extra, err := config.RepoEnv(repo)
	if err != nil {
		return nil, err
	}
	on := &branch{repo: repo, root: root, clean: clean, env: slices.Clone(clean)}
	for key, value := range extra {
		on.env = append(on.env, key+"="+value) // exec keeps a key's last value
	}
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
	on.sha = run("rev-parse", "--verify", cmp.Or(at, base)+"^{commit}")
	on.commit = run("log", "-1", "--format=%h %s", "--abbrev=12", on.sha)
	if err != nil {
		return nil, err
	}
	return on, os.MkdirAll(filepath.Join(config.Home(), "wt"), 0o700)
}

// checkout runs fn in a clean checkout of the branch made for it alone, so nothing one check
// writes is there for the next, and removed after it.  It sits beside runs' checkouts in
// ~/.agentkit/wt, where ak's history reads a test's fixtures as a run's.
func (on *branch) checkout(ctx context.Context, fn func(tree string) error) error {
	tmp, err := os.MkdirTemp(filepath.Join(config.Home(), "wt"), "plan-")
	if err != nil {
		return err
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
		return fmt.Errorf("cannot check %s's default branch: %w", filepath.Base(on.repo), err)
	}
	return fn(tree)
}

// passes is whether check passes in tree; one that does not finish within checkLimit is an error.
func (on *branch) passes(ctx context.Context, tree, check string) (bool, error) {
	limited, cancel := context.WithTimeout(ctx, checkLimit)
	defer cancel()
	cmd := exec.CommandContext(limited, "bash", "-c", check)
	cmd.Dir, cmd.Env = tree, on.env
	stop := host.Group(cmd)
	if err := cmd.Start(); err != nil {
		return false, err
	}
	err := cmd.Wait()
	stop() // no child outlives the checkout
	if limited.Err() != nil && ctx.Err() == nil {
		return false, fmt.Errorf("this check did not finish within %d s; an unfinished check proves nothing", checkLimit/time.Second)
	}
	return err == nil, ctx.Err()
}

// rootOf is the repository a checkout holds, as no other one can: its first root commit, abbreviated.
func rootOf(env []string, dir string) string {
	out, _ := git(context.Background(), env, dir, "rev-list", "--max-parents=0", "HEAD")
	roots := strings.Fields(out)
	if len(roots) == 0 {
		return ""
	}
	return slices.Min(roots)[:12]
}

// named is how a line names the checkout it was written under, for good: its path (`~` for
// home) and the repository there, by the root commit found where its check ran.
func named(repo, found string) string {
	shown := config.Resolve(repo)
	if rel, err := filepath.Rel(config.Resolve(home()), shown); err == nil && filepath.IsLocal(rel) {
		shown = "~/" + rel
	}
	if found == "" {
		return shown
	}
	return shown + "#" + found
}

// holdsCheckout refuses a check whose text holds the path of the project's checkout: a check
// runs in a clean checkout of the default branch, and one that goes to the seat's tests what
// that holds instead.  It reads text, not the shell: the path as written from `/`, `~`, `$HOME`
// or `${HOME}`, with every quote and backslash dropped from both, so any quoting of it is found
// and a longer name that starts with it (`acme-old`) is refused too.
func holdsCheckout(check, repo string) error {
	var paths []string
	for _, path := range []string{filepath.Clean(repo), config.Resolve(repo)} {
		paths = append(paths, path)
		for _, top := range []string{home(), config.Resolve(home())} {
			if rel, err := filepath.Rel(top, path); err == nil && filepath.IsLocal(rel) {
				paths = append(paths, "~/"+rel, "$HOME/"+rel, "${HOME}/"+rel)
			}
		}
	}
	slices.Sort(paths)
	shown := slices.MinFunc(paths, func(a, b string) int { return len(a) - len(b) })
	for _, path := range paths {
		if strings.Contains(quotes.Replace(check), quotes.Replace(path)) {
			return fmt.Errorf("this check holds %s, the path of the project's checkout, but a check runs in a clean "+
				"checkout of its default branch: name paths relative to the repository, as in `python3 tests/test_x.py`", shown)
		}
	}
	return nil
}

var quotes = strings.NewReplacer(`"`, "", "'", "", `\`, "")

func home() string {
	home, _ := os.UserHomeDir()
	return filepath.Clean(home)
}
