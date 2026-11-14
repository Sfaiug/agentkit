package update

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
	"agentkit/internal/tmux"
)

// LiveVerb is the unlisted command the tick starts a check of agentkit's tests/live.sh with, `ak
// live-check <folder>` (LiveCheck), where Python's starts LIVE_RUN: Go and git are all it needs.
const LiveVerb = "live-check"

// startLive is how Python's live_tick ends once no check of tip runs or passed: held while a login
// it lends lapses within its margin, said once, else started from the checkout: git's own gc off
// there, said, its folder `<tip>-<started>` under state/live-checks, and LiveCheck started for it,
// detached, as unit agentkit-live-<folder> in ak's own slice, its output nowhere, with env, the
// child environment and the pins.  Reading the check on record stays Python's (LiveReady).
// Unlike Python's, a scope it goes in is not stopped when the check ends: what the check left
// outside its group runs on in it, until the tick ends what carries the check's marker.
func startLive(checkout, tip string, env []string, say func(string)) error {
	self, err := os.Executable()
	if err != nil {
		return ErrPython // Python's runner needs no program of Go's
	}
	if waitsForLogin("live", "tests/live.sh", margin("live", liveCap), now(), say) {
		return nil
	}
	if err := gitcall.NoAutoGC(checkout); err != nil {
		return err
	}
	say(fmt.Sprintf("checking agentkit at %s with tests/live.sh before it goes live", short(tip)))
	checks := filepath.Join(config.Home(), "state", "live-checks")
	folder := filepath.Join(checks, fmt.Sprintf("%s-%d", tip, int64(now())))
	if err := os.MkdirAll(checks, 0o777); err != nil {
		return err
	}
	if err := os.Mkdir(folder, 0o777); err != nil {
		return err
	}
	cmd := exec.Command(self, LiveVerb, folder)
	cmd.Env = host.Unmarked(append(slices.Clip(env), "AGENTKIT_ACCEPTANCE_REQUIRED=1", host.Marker+"="+folder))
	_, _, _, err = host.PlaceIn(tmux.Own()+".slice", cmd, os.DevNull, "agentkit-live-"+filepath.Base(folder), nil, true)
	return err
}
