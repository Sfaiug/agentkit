package seat

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
)

// A stand is a checkout that stands for a project, and that project's checkout: agentkit's own
// for a second clone of it, else itself.
type stand struct{ checkout, project string }

// homeKey is where the menu files a seat by its repo (orch.home_key): projects by name, then
// the seats filed under none. `stands` looks at ~/code only once a repo asks.
func homeKey(repo string, stands func() []stand) []string {
	if checkout := checkoutOf(repo, stands); checkout != "" {
		return []string{"0", base(checkout), checkout}
	}
	return []string{"1", "", ""}
}

// checkoutOf is the checkout a repo path is (orch.checkout_of): one that stands for a project,
// a worktree added from one, or a path directly under ~/code named as one's project; "" for none.
func checkoutOf(repo string, stands func() []stand) string {
	if repo == "" {
		return ""
	}
	path := config.Resolve(repo)
	for _, each := range stands() {
		if config.Resolve(each.checkout) == path {
			return each.project
		}
	}
	if git := dirsOf(path); git.known && git.added {
		for _, each := range stands() {
			if other := dirsOf(each.checkout); other.known && other.common == git.common {
				return each.project
			}
		}
	}
	home, _ := os.UserHomeDir()
	if filepath.Dir(path) == config.Resolve(filepath.Join(home, "code")) {
		for _, each := range stands() {
			if base(each.project) == base(path) {
				return each.project
			}
		}
	}
	return ""
}

// listed is every checkout that stands for a project (orch.listed): one directly under ~/code
// that is no worktree of another listed, and agentkit's own at ~/agentkit, whose second clone
// stands for it.
func listed() []stand {
	home, _ := os.UserHomeDir()
	code, own := filepath.Join(home, "code"), filepath.Join(home, "agentkit")
	var found []string
	entries, _ := os.ReadDir(code)
	for _, entry := range entries {
		path := filepath.Join(code, entry.Name())
		if info, err := os.Stat(path); err == nil && info.IsDir() && exists(filepath.Join(path, ".git")) {
			found = append(found, path)
		}
	}
	dirs, stands, mains := map[string]gitDirs{}, map[string]bool{}, map[string]bool{}
	for _, path := range append(slices.Clone(found), own) {
		dirs[path] = dirsOf(path)
		if dirs[path].known && (!dirs[path].added || path == own || base(path) == base(own)) {
			stands[path], mains[dirs[path].common] = true, true
		}
	}
	found = slices.DeleteFunc(found, func(path string) bool {
		return !stands[path] && dirs[path].known && mains[dirs[path].common]
	})
	var listing []stand
	if !exists(filepath.Join(own, ".git")) || slices.ContainsFunc(found, func(path string) bool {
		return config.Resolve(path) == config.Resolve(own)
	}) {
		for _, path := range found {
			listing = append(listing, stand{path, path})
		}
		return listing
	}
	for _, path := range append(found, own) {
		project := path
		if base(path) == base(own) {
			project = own
		}
		listing = append(listing, stand{path, project})
	}
	return listing
}

// gitDirs is what git says of a checkout: its repository's common git directory and whether it
// is a worktree added from another checkout; not known where it is no checkout.
type gitDirs struct {
	common       string
	added, known bool
}

// dirsOf is orch.git_dirs: a plain `.git` directory with no `commondir` is a repository's own
// checkout; for anything else git itself is asked.
func dirsOf(path string) gitDirs {
	dot := filepath.Join(path, ".git")
	info, err := os.Lstat(dot)
	if err != nil {
		return gitDirs{}
	}
	if info.IsDir() && !exists(filepath.Join(dot, "commondir")) {
		return gitDirs{config.Resolve(dot), false, true}
	}
	gitdir, ok := askGit(path, "--git-dir")
	common, same := askGit(path, "--git-common-dir")
	if !ok || !same {
		return gitDirs{}
	}
	return gitDirs{common, gitdir != common, true}
}

// askGit is the path git names for a flag, asked at `path` alone, never above it, with nothing
// of git's own environment: an inherited repository would answer for another checkout.
func askGit(path, flag string) (string, bool) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", "rev-parse", "--path-format=absolute", flag)
	cmd.Dir = path
	for _, each := range os.Environ() {
		if !strings.HasPrefix(each, "GIT_") {
			cmd.Env = append(cmd.Env, each)
		}
	}
	cmd.Env = append(cmd.Env, "GIT_CEILING_DIRECTORIES="+filepath.Dir(path))
	out, err := cmd.Output()
	if err != nil {
		return "", false
	}
	return config.Resolve(strings.TrimSuffix(string(out), "\n")), true
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
