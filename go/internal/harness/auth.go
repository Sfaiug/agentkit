package harness

import (
	"os"
	"strings"
	"unicode"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// An Answer is a harness's login read for its adapter's `auth`: whether a turn, or the seat, can
// sign in on it, the one line saying so, and whether it lapsed where only a turn of the harness
// renews it.
type Answer struct {
	Yes, Lapsed bool
	Line        string
}

// Auth is that harness's login read for a turn, or with seat for the seat's own, on login; false
// where Go does not read that harness's login yet.
func Auth(name string, login config.Login, seat bool) (Answer, bool) {
	if hook := plugins[name].auth; hook != nil {
		return hook(login, seat), true
	}
	return Answer{}, false
}

// Usage is that harness's reading of its subscription's meters on a login, its adapter's `usage`
// answer as one JSON line; nil where Go does not read that harness's meters yet.
func Usage(name string) func(login config.Login) string {
	hook := plugins[name].usage
	if hook == nil {
		return nil
	}
	return func(login config.Login) string { return run.Line(hook(login)) }
}

// getenv is the variable as a call on the login sees it.
func getenv(login config.Login, name string) (value string) {
	for _, pair := range login.Environ(os.Environ()) {
		if key, set, _ := strings.Cut(pair, "="); key == name {
			value = set
		}
	}
	return value
}

// given is whether jq's `// ""` keeps a JSON value: anything but a missing one, null, false and "".
func given(value any) bool {
	return value != nil && value != false && value != ""
}

// blank is whether text holds nothing but white space.
func blank(text string) bool {
	return strings.TrimFunc(text, unicode.IsSpace) == ""
}
