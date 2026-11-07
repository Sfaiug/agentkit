package update

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/lend"
	"agentkit/internal/worker"
)

// A check lends each harness's login to a throwaway HOME as a copy nothing renews, so a login
// that lapses while the check runs fails it for nothing the code did: a check waits for a tick
// whose logins outlast it.

// margin is how long the logins a run of check key ("live" or "fresh") borrows must last, as
// Python's update.margin: its last pass's time doubled, never past limit, its cap, which is the
// margin where none passed.
func margin(key string, limit float64) float64 {
	var last []float64
	data, err := os.ReadFile(filepath.Join(config.Home(), "state", key+"-check-passed"))
	if err != nil || json.Unmarshal(data, &last) != nil || len(last) != 2 {
		return limit
	}
	return min(2*last[1], limit)
}

// waitsForLogin is whether what, started by a tick at at, waits for a later tick, as Python's
// update._waits_for_login: a login lent to it lapses within seconds of its start.  The log hears
// it once: state/<key>-check-held keeps what it heard, gone once what starts.
func waitsForLogin(key, what string, seconds, at float64, say func(string)) bool {
	heard := filepath.Join(config.Home(), "state", key+"-check-held")
	ends, whose, lapses := firstLapse()
	// it starts once all asking ends, never before the tick's at: a release's lookup, `auth
	// seat` and lending can each take minutes of a login's life
	if !lapses || float64(ends) >= max(at, now())+seconds {
		os.Remove(heard)
		return false
	}
	line := fmt.Sprintf("%s waits: %s's login lapses at %s, before it could end", what, whose,
		time.Unix(ends, 0).Format("2006-01-02 15:04"))
	if was, err := os.ReadFile(heard); err != nil || string(was) != line {
		say(line)
		put(heard, []byte(line))
	}
	return true
}

// firstLapse is the epoch second the first login lent to a check started now lapses, and whose,
// as Python's lend.first_lapse: false where none lapses, or a lend fails, which that check says.
// Each lender's `auth seat` runs first, in this HOME, so a lapsed login its adapter renews in
// place is lent fresh.
func firstLapse() (int64, string, bool) {
	lenders, err := lend.Lenders()
	env, unread := config.ChildEnv()
	if err != nil || unread != nil {
		return 0, "", false
	}
	for _, name := range lenders {
		adapter, err := config.LoginAdapter(name)
		if err != nil {
			return 0, "", false
		}
		worker.Login(adapter, append(slices.Clip(env), "AGENTKIT_PROVIDER="+strings.Join(config.HarnessProviders(name), " ")), "seat")
	}
	home, err := os.MkdirTemp(filepath.Join(config.Home(), "tmp"), "lend-")
	if err != nil {
		return 0, "", false
	}
	defer os.RemoveAll(home)
	loan, err := lend.Into(home, false)
	return loan.Ends, loan.Whose, err == nil && loan.Whose != ""
}
