// Package harness holds what a harness brings beyond its adapter's manifest, as Python's
// agentkit/harness/<name>.py does: each hook answered by that harness's own where it has one,
// by the default elsewhere.
package harness

import (
	"cmp"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
)

// A plugin is one harness's own answers; a hook it leaves nil takes the default.
type plugin struct {
	identity func(text string, argv []string) (string, bool)
	// seats is whether Go follows this harness's seats tmux no longer holds, and fresh what
	// reopening one does where it owns no conversation its record names.
	seats   bool
	fresh   string
	answer  func(conversation, cwd string) (model, effort any, found bool)
	turnEnv map[string]string
	auth    func(login config.Login, seat bool) Answer
	lend    func(login config.Login) Loan
	// opens is whether Go opens this harness's seats: Python's launch writes down the launcher's
	// conversation id alone (the default `launched`), and titled whether its TUI takes a title
	// line (`title_command`).
	opens, titled bool
	// paysItsOwnWay is whether its own config says how a model of it is paid, over config.toml's
	// `mode`, as Python's plugin `mode` reads it.
	paysItsOwnWay bool
}

var plugins = map[string]plugin{}

// Identity is a harness's `[update] version` output as a build identity, refined where it has
// more to say; false where it reads what Go cannot read as Python does.
func Identity(name, text string, argv []string) (string, bool) {
	if hook := plugins[name].identity; hook != nil {
		return hook(text, argv)
	}
	return text, true
}

// Reopens is what reopening a seat of that harness only its record holds does, as Python's
// plugin `restart_word` says it: "" where it resumes the conversation its record names; false
// where Go does not follow that harness's seats yet.
func Reopens(name string) (string, bool) {
	return plugins[name].fresh, plugins[name].seats
}

// Opens is whether a launch of that harness's seat writes down its title, as Python's plugin
// `title_command` and the manifest's `[title] at_launch` say; false where Go does not open that
// harness's seats yet.
func Opens(name string) (titled, known bool) {
	if !plugins[name].opens {
		return false, false
	}
	title, err := config.Section(name, "title")
	at, set := title["at_launch"].(bool)
	return plugins[name].titled && (!set || at), err == nil
}

// LastAnswer is the model and effort of the last answer a seat's conversation records, as
// Python's plugin `running` reads it; false where that harness records none Go reads.
func LastAnswer(name, conversation, cwd string) (model, effort any, found bool) {
	if hook := plugins[name].answer; hook != nil {
		return hook(conversation, cwd)
	}
	return nil, nil, false
}

// PaysItsOwnWay is whether that harness's own config says how a model of it is paid, which Go
// does not read yet.
func PaysItsOwnWay(name string) bool {
	return plugins[name].paysItsOwnWay
}

// TurnEnv is what a worker turn of that harness is told beyond what every turn is, none by
// default.
func TurnEnv(name string) map[string]string {
	return plugins[name].turnEnv
}

// Binary is the program a harness's command names, found as its adapter finds it, as Python's
// config.harness_binary: on PATH first, else in an installer's own folder no fresh shell has on
// PATH; a path answers for itself.  "" where it is not found.
func Binary(name string) string {
	if strings.Contains(name, "/") {
		if _, err := exec.LookPath(name); err == nil {
			return name
		}
		return ""
	}
	// Python's which takes a relative PATH entry as it takes any other
	if found, err := exec.LookPath(name); err == nil || errors.Is(err, exec.ErrDot) {
		return found
	}
	home, _ := os.UserHomeDir()
	for _, dir := range []string{filepath.Join(home, ".opencode", "bin"),
		cmp.Or(os.Getenv("GROK_BIN_DIR"), filepath.Join(home, ".grok", "bin")),
		filepath.Join(home, ".local", "bin"), filepath.Join(home, ".npm-global", "bin")} {
		if found, err := exec.LookPath(filepath.Join(dir, name)); err == nil {
			return found
		}
	}
	return ""
}
