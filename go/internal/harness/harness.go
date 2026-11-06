// Package harness holds what a harness brings beyond its adapter's manifest, as Python's
// agentkit/harness/<name>.py does: each hook answered by that harness's own where it has one,
// by the default elsewhere.
package harness

import (
	"cmp"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/hookfact"
	"agentkit/internal/run"
)

// A plugin is one harness's own answers; a hook it leaves nil takes the default.
type plugin struct {
	identity    func(text string, argv []string) (string, bool)
	interactive func(root string, args []string, out, errOut io.Writer) int
	seatWords   func(words, env []string) []string
	hookEvent   func(event *run.Object) *run.Object
	// seats is whether Go follows this harness's seats tmux no longer holds, and fresh what
	// reopening one does where it owns no conversation its record names.
	seats   bool
	fresh   string
	receipt string
	answer  func(record *run.Object) (model, effort, at any, found bool)
	// conversation is the file a seat's record says its conversation is kept in, "" for none.
	conversation func(record map[string]any) string
	// owns is whether the record vouches for that conversation as the seat's own (orch.owns), and
	// resumable whether the seat owns one it may resume, where its own evidence says so, not its
	// record (orch.resumable).
	owns      func(record *run.Object, conversation string) bool
	resumable func(record *run.Object) bool
	// record freezes the evidence of a record Go leaves to Python to reconcile; false hands it
	// back before writing. The returned hooks use that evidence throughout this listing.
	// keys and kept are the record keys and state/ files this harness keeps beyond everyone's.
	record func(name string, record *run.Object) (plugin, bool)
	heard  func(name string) hookfact.Fact
	keys   []string
	kept   *regexp.Regexp
	// notices is how each manifest frame that is a notice all its own ends: the manifest names one
	// only by what opens it, and an owner who goes on after one wrote the rest themselves.
	notices map[string][]string
	turnEnv map[string]string
	auth    func(login config.Login, seat bool) Answer
	lend    func(login config.Login) Loan
	// looks is whether Go reads the screen of this harness's seats, and recorded the error its
	// conversation ends on (Python's plugin `error`).
	looks    bool
	recorded func(record *run.Object) (string, bool)
	// last is the last message of the conversation, its owner's or its model's, nil for none, and
	// notices above say which of them only record the owner interrupting.
	last func(conversation, cwd, account string) *run.Object
	// opens is whether Go opens this harness's seats: Python's launch writes down the launcher's
	// conversation id alone (the default `launched`), and titled whether its TUI takes a title
	// line (`title_command`).
	opens, titled bool
	launch        func() (*run.Object, []string)
	launched      func(string, string, *run.Object) (*run.Object, []string, error)
	retire        func(*run.Object) error
	handed        func(*run.Object) (string, bool)
	moveReady     func() bool
	// paysItsOwnWay is whether its own config says how a model of it is paid, over config.toml's
	// `mode`, as Python's plugin `mode` reads it.
	paysItsOwnWay bool
	// usageTaken and usageRecorded are UsageTaken's and UsageRecorded's: nil where a usage read
	// says when it measured and the harness writes no refusal's meters down.
	usageTaken    func(data *run.Object, state string) any
	usageRecorded func(state string, now float64) []*run.Object
	// recordTurn is RecordTurn's: nil where a turn reports no refusal of its own.
	recordTurn func(out, state, account string)
	// failed is TurnFailed's: nil where a failed turn's stderr holds all it says of why.
	failed func(out string, result map[string]any)
	// registerMCP is RegisterMCP's: nil where its plugin writes no MCP entry.
	registerMCP func(servers []Server) (string, error)
	// title is SessionTitle's: nil where its conversation keeps no title Go reads.
	title func(record *run.Object, cache string) (any, *run.Object)
	// wrapped is WrappedUp's: nil where its conversation notes no turn wrapped up for its limit.
	wrapped func(record map[string]any, prompted func(*run.Object) bool) any
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
	own := seatDefaults(name)
	return own.fresh, own.seats
}

// Receipt is the key of a seat's record that names that harness's evidence of the conversation it
// owns, which Go does not verify yet; "" where the record alone says.
func Receipt(name string) string {
	return plugins[name].receipt
}

// Opens is whether a launch of that harness's seat writes down its title, as Python's plugin
// `title_command` and the manifest's `[title] at_launch` say; false where Go does not open that
// harness's seats yet.  A harness named nowhere here is a manifest and an adapter, whose every
// hook is the default.
func Opens(name string) (titled, known bool) {
	if own, named := plugins[name]; named && !own.opens {
		return false, false
	}
	title, err := config.Section(name, "title")
	at, set := title["at_launch"].(bool)
	return plugins[name].titled && (!set || at), err == nil
}

// LastAnswer is the model, effort and time of the last answer a seat's conversation records, as
// Python's plugin `running` reads them; false where that harness records none Go reads.
func (reader Reader) LastAnswer(record *run.Object) (model, effort, at any, found bool) {
	if hook := reader.own.answer; hook != nil {
		return hook(record)
	}
	return nil, nil, nil, false
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
