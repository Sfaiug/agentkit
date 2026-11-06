package update

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
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
// A lender is a harness whose manifest lists `[worker] logins`, with an adapter here.  Each one's
// `auth seat` runs first, in this HOME, so a lapsed login its adapter renews in place is lent fresh.
func firstLapse() (int64, string, bool) {
	names, err := config.ManifestNames()
	env, unread := config.ChildEnv()
	if err != nil || unread != nil {
		return 0, "", false
	}
	adapters := map[string]string{}
	for _, name := range names {
		logins, _ := config.Words(name, "worker", "logins")
		if adapter, err := config.LoginAdapter(name); len(logins) > 0 && err == nil {
			adapters[name] = adapter
			worker.Login(adapter, append(slices.Clip(env), "AGENTKIT_PROVIDER="+strings.Join(providers(name), " ")), "seat")
		}
	}
	home, err := os.MkdirTemp(filepath.Join(config.Home(), "tmp"), "lend-")
	if err != nil {
		return 0, "", false
	}
	defer os.RemoveAll(home)
	lend := append(os.Environ(), "AGENTKIT_ACCOUNT=", "AGENTKIT_PROVIDER=")
	first, whose := int64(0), ""
	for _, name := range names {
		if adapters[name] == "" {
			continue
		}
		staging, err := os.MkdirTemp(home, ".lend-")
		if err != nil {
			return 0, "", false
		}
		stdout, _, code, err := output(lend, time.Minute, adapters[name], "lend", staging)
		if err == nil && code == 1 {
			continue // none to lend
		}
		said := strings.TrimFunc(string(stdout), config.Space)
		ends, unread := strconv.ParseInt(said, 10, 64)
		if err != nil || code != 0 || !utf8.Valid(stdout) || said != "" && unread != nil {
			return 0, "", false
		}
		if said != "" && (whose == "" || ends < first) {
			first, whose = ends, name
		}
	}
	return first, whose, whose != ""
}

// providers is each provider whose offered models the config runs on that harness, once, as
// Python's config.harness_providers: what a question about the harness as a whole asks about.
func providers(harness string) []string {
	offered, _ := config.Offered()
	var found []string
	for _, name := range offered {
		if model, err := config.ModelNamed(name); err == nil && model.Harness == harness && !slices.Contains(found, model.Provider) {
			found = append(found, model.Provider)
		}
	}
	return found
}
