package config

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
)

// RunCode is where Python's versions.enter names the version a run is pinned to (CODE_ENV), which
// nothing outliving that run carries.
const RunCode = "AK_RUN_CODE"

// Running is this program, its links resolved, and ~/agentkit's build of it, the two paths
// Python's update_first compares: a worktree nested inside ~/agentkit is not on it.
func Running() (self, live string, err error) {
	self, err = os.Executable()
	if err != nil {
		return "", "", err
	}
	self = Resolve(self)
	return self, filepath.Join(Resolve(filepath.Join(UserHome(), "agentkit")), "go", "bin", filepath.Base(self)), nil
}

// Live is the program a seat runs, and its server runs for it, as Python's versions.live names
// the checkout: ~/agentkit's build, whichever process opens the seat (one a swap has since moved
// under ~/.agentkit/versions, a worktree's, another clone's), as a seat outlives them all; this
// program where ~/agentkit holds no build.
func Live() (string, error) {
	program, _, err := live()
	return program, err
}

// LiveRepo is the checkout Live lies in: ~/agentkit, else Repo.
func LiveRepo() string {
	if program, built, _ := live(); built {
		return filepath.Dir(filepath.Dir(filepath.Dir(program)))
	}
	return Repo()
}

// live is Live, and whether it is ~/agentkit's build.
func live() (string, bool, error) {
	self, build, err := Running()
	if info, missing := os.Stat(build); err == nil && missing == nil && info.Mode().IsRegular() {
		return build, true, nil
	}
	return self, false, err
}

// Unpinned is the PATH list path without an entry under ~/.agentkit/versions, for what outlives
// this process: an `ak` found there would run that version.  Python's versions.unpinned drops a
// version's bin; Go's build lies deeper, in its go/bin, so every entry under the folder goes.
func Unpinned(path string) string {
	versions := filepath.Join(Home(), "versions")
	kept := slices.DeleteFunc(filepath.SplitList(path), func(entry string) bool {
		entry = filepath.Clean(entry)
		return entry == versions || strings.HasPrefix(entry, versions+string(filepath.Separator))
	})
	return strings.Join(kept, string(os.PathListSeparator))
}
