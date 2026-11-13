package config

import (
	"os"
	"path/filepath"
)

// RunCode is where Python's versions.enter names the version a run is pinned to (CODE_ENV), which
// nothing outliving that run carries.
const RunCode = "AK_RUN_CODE"

// Running is this program, its links resolved, and ~/agentkit's build, go/bin/ak whatever this
// program is called: a copy named otherwise still hands its seats the installed ak.
func Running() (self, live string, err error) {
	self, err = os.Executable()
	if err != nil {
		return "", "", err
	}
	return Resolve(self), filepath.Join(Resolve(filepath.Join(UserHome(), "agentkit")), "go", "bin", "ak"), nil
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
