package harness

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func init() { plugins["grokbuild"] = plugin{auth: grokAuth, lend: grokLend} }

// dated is an ISO-8601 instant, which sorts as a string: Grok's `expires_at`.
var dated = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T`)

// grokAuth reads Grok Build's one login as grokbuild.sh's `auth` does, the seat's as a turn's:
// the usual login's key in the environment, else an entry of its file with an unexpired key, or
// with a refresh token, which grok trades for a fresh key itself whenever it starts.  A key that
// grok renewed and the billing endpoint still refused is a logout only `usage` writes down.
func grokAuth(login config.Login, _ bool) Answer {
	for _, variable := range login.Unset {
		if getenv(login, variable) != "" {
			return Answer{Yes: true, Line: "grok: " + variable + " is set"}
		}
	}
	file, data, value, entries := grokLogin(login)
	no := func(line string) Answer { return Answer{Line: "grok: " + line + "; run `grok login`"} }
	switch {
	case blank(string(data)):
		return no("no " + file)
	case value == nil:
		return no(file + " is not JSON")
	}
	some := func(test func(entry *run.Object) bool) bool { return slices.ContainsFunc(entries, test) }
	refused, _ := os.ReadFile(config.LoginPath("grokbuild", "refused", login))
	if at := slices.IndexFunc(entries, grokKeyed); at >= 0 {
		digest := sha256.Sum256([]byte(entries[at].Str("key")))
		if strings.TrimRight(string(refused), "\n") == hex.EncodeToString(digest[:]) {
			return no("the billing endpoint refused the login in " + file + " after grok's own renewal")
		}
	}
	now := time.Now().UTC().Format("2006-01-02T15:04:05Z")
	switch {
	case some(func(entry *run.Object) bool {
		ends := entry.Str("expires_at")
		return grokKeyed(entry) && dated.MatchString(ends) && ends > now
	}):
		return Answer{Yes: true, Line: "grok: the login in " + file + " is saved"}
	case some(func(entry *run.Object) bool { return !blank(entry.Str("refresh_token")) }):
		return Answer{Yes: true, Line: "grok: the login in " + file + " is saved; grok renews its lapsed key itself"}
	case !some(grokKeyed):
		return no(file + " carries no session token")
	case some(func(entry *run.Object) bool { return given(entry.Get("expires_at")) }):
		return no("the login in " + file + " is expired")
	}
	return no(file + " records no usable expiry")
}

// grokLogin is Grok Build's one login: the file it is kept in, the text read, that text as JSON
// where `jq -e .` takes it, else nil, and each object it holds, an entry.
func grokLogin(login config.Login) (file string, data []byte, value any, entries []*run.Object) {
	file = config.LoginPath("grokbuild", "credentials", login)
	data, _ = os.ReadFile(file)
	value, err := run.Decode(data)
	if err != nil || value == false {
		value = nil
	}
	if whole, ok := value.(*run.Object); ok {
		for _, key := range whole.Keys() {
			if entry, ok := whole.Get(key).(*run.Object); ok {
				entries = append(entries, entry)
			}
		}
	}
	return file, data, value, entries
}

// grokKeyed is whether an entry holds a session key.
func grokKeyed(entry *run.Object) bool {
	return !blank(entry.Str("key"))
}
