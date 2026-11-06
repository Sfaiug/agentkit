package seat

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"

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

// Checkouts is every project's checkout on this machine, by name (orch.checkouts), and false
// where a look fails: listed passes over a place it cannot read, which may hold one.
func Checkouts() ([]string, bool) {
	if !checkoutsSeen() {
		return nil, false
	}
	var found []string
	for _, each := range listed() {
		if !slices.Contains(found, each.project) {
			found = append(found, each.project)
		}
	}
	slices.SortStableFunc(found, func(a, b string) int { return strings.Compare(base(a), base(b)) })
	return found, true
}

// Common is the common git directory of the checkout at path (orch.git_dirs), false for none.
func Common(path string) (string, bool) {
	dirs := dirsOf(path)
	return dirs.common, dirs.known
}

// checkoutsSeen is whether a look at every place a checkout may stand succeeded.
func checkoutsSeen() bool {
	home, _ := os.UserHomeDir()
	code := filepath.Join(home, "code")
	entries, err := os.ReadDir(code)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return false
	}
	places := []string{filepath.Join(home, "agentkit")}
	for _, entry := range entries {
		places = append(places, filepath.Join(code, entry.Name()))
	}
	return !slices.ContainsFunc(places, unseen)
}

// unseen is whether a look at a place, or at the `.git` a folder there would hold, failed on
// anything but nothing being there.
func unseen(path string) bool {
	info, err := os.Stat(path)
	if err == nil && info.IsDir() {
		_, err = os.Stat(filepath.Join(path, ".git"))
	}
	return err != nil && !errors.Is(err, fs.ErrNotExist)
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
// checkout; for anything else git itself is asked, once in gitHeld.
func dirsOf(path string) gitDirs {
	dot := filepath.Join(path, ".git")
	info, err := os.Lstat(dot)
	if err != nil {
		return gitDirs{}
	}
	if info.IsDir() && !exists(filepath.Join(dot, "commondir")) {
		return gitDirs{config.Resolve(dot), false, true}
	}
	return askedDirs(path)
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
