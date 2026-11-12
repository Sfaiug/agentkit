package gitcall

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// stops is what each git command that can stop part way leaves in a checkout's own git directory
// until it is finished or aborted, Python's gitcall.STOPS.
var stops = map[string][]string{
	"rebase":      {"rebase-merge", "rebase-apply"},
	"merge":       {"MERGE_HEAD"},
	"cherry-pick": {"CHERRY_PICK_HEAD", "sequencer"},
}

// InProgress is whether a `git <how>` of hows, every one stops knows where hows names none, is
// still sitting unfinished in the checkout, Python's in_progress: its own git directory's name is
// kept byte for byte, as split into lines or trimmed, a newline or a trailing space in it would
// hide the state.
func InProgress(g Git, hows ...string) (bool, error) {
	code, out, said, err := g.Bytes("rev-parse", "--absolute-git-dir")
	if err != nil {
		return false, err
	}
	if code != 0 {
		return false, fmt.Errorf("git rev-parse --absolute-git-dir failed in %s: %s", g.Repo, Strip(string(said)))
	}
	own := strings.TrimSuffix(string(out), "\n")
	if len(hows) == 0 {
		for how := range stops {
			hows = append(hows, how)
		}
	}
	for _, how := range hows {
		for _, name := range stops[how] {
			if _, err := os.Stat(filepath.Join(own, name)); err == nil {
				return true, nil
			}
		}
	}
	return false, nil
}
