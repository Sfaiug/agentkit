package seat

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/adapters"
	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// serverWide is what Python's tmux.conf sets on ak's server, but its pane-died hook and Ctrl-b
// m, which run Python's ak: a touch scrolls a seat's output, 50000 lines of it; a harness that
// ends keeps its pane; a link it prints reaches the owner's terminal whole.
var serverWide = []string{"set-option", "-g", "mouse", "on", ";", "set-option", "-g", "history-limit", "50000", ";",
	"set-option", "-g", "remain-on-exit", "on", ";", "set-option", "-g", "allow-passthrough", "on", ";",
	"set-option", "-as", "terminal-features", ",*:RGB:hyperlinks", ";"}

// Open is Python's orch.create and launch of a new seat a person names with both its models,
// in a home Python's maintenance finds tidy, filed under no project and on a provider listing no
// accounts: its rulebook, its command from its harness's adapter, its record, [defaults]
// remembering its models, and its session on ak's server, ak's shims first on its harness's
// PATH.  False where Python's open does what Go does not yet: a harness whose launch writes down
// more than the conversation it hands out, a name a gone seat left files under, a folder that is
// a checkout of its own, whose git ak keeps from collecting, reviewers Go binds otherwise, or an
// adapter giving no command, where only the rulebook is written.
func Open(name, orchestrator string, model config.Model, workers []string, cwd string) (bool, error) {
	state := filepath.Join(config.Home(), "state")
	titled, known := harness.Opens(model.Harness)
	bound, unbound := config.Bind()
	models, err := config.Models()
	if !known || !unclaimed(state, name, cwd) || unbound != nil || err != nil {
		return false, nil
	}
	// written before its adapter is asked, which may read it, and gone again where no seat comes
	// of it: unclaimed takes a file left under the name for a gone seat's
	rulebook := filepath.Join(state, "rulebook-"+name+".md")
	text, err := Rulebook()
	if err != nil || os.WriteFile(rulebook, []byte(text), 0o666) != nil {
		os.Remove(rulebook)
		return false, nil
	}
	created := seconds(time.Now())
	cmd, conversation, ok := adapters.Command(model, append(os.Environ(), "AGENTKIT_SESSION="+name, "AGENTKIT_SEAT_REPO=",
		"AGENTKIT_RULEBOOK="+rulebook, "AGENTKIT_FIRST_PROMPT="))
	if !ok {
		os.Remove(rulebook)
		return false, nil
	}
	fields := []field{{"orchestrator", orchestrator}, {"workers", modelList(workers)}}
	var reviewers []string
	for _, each := range bound.Reviewers {
		reviewers = append(reviewers, each.(string))
	}
	if reviewers != nil {
		fields = append(fields, field{"reviewers", modelList(reviewers)})
	}
	fields = append(fields, field{"cwd", cwd}, field{"repo", nil}, field{"created", created}, field{"account", nil}, field{"home_account", nil})
	if conversation != "" {
		fields = append(fields, field{"conversation", conversation}, field{"id_source", "launcher"})
	}
	// where and when, and the conversation it owns: what opens the seat again once tmux has lost it
	err = put(filepath.Join(state, "session-"+name+".json"), filepath.Join(state, ".session-"+name+".lock"), run.Encode, true, func(data *run.Object) bool {
		for _, f := range fields {
			data.Set(f.key, f.value)
		}
		ownEfforts(data, name, models)
		return true
	})
	if err != nil {
		return true, err
	}
	config.RememberDefaults(orchestrator, workers, reviewers) // a seat is made all the same
	if err := forgetSeen(state, name, time.Now()); err != nil {
		return true, err
	}
	read, _ := os.ReadFile(rulebook)
	sum := sha256.Sum256(read)
	// under the seat's lock, as a rename going on keeps its record
	err = notify.Held(context.Background(), name, func(current string) error {
		// before the harness is up: its first prompt may be offered a newer rulebook already
		if err := update(state, current, func(data *run.Object) bool {
			data.Set("resumable", conversation != "")
			data.Set("rulebook_sha", hex.EncodeToString(sum[:]))
			return true
		}); err != nil {
			return err
		}
		if err := start(state, current, cwd, cmd); err != nil {
			// no harness read them
			update(state, current, func(data *run.Object) bool {
				data.Delete("resumable")
				data.Delete("rulebook_sha")
				return true
			})
			return err
		}
		// the moment from which an answer is this harness's
		return update(state, current, func(data *run.Object) bool {
			data.Set("launched", seconds(time.Now()))
			return true
		})
	})
	if err == nil && titled {
		err = update(state, name, func(data *run.Object) bool {
			data.Set("session_title", name)
			return true
		})
	}
	return true, err
}

// Attach hands this terminal to the seat's session, as Python's orch.attach does from a
// person's: tmux run as a terminal this box knows, the seat seen opened, then tmux's client in
// this process's place.  It answers only where it could not.
func Attach(name string, out, errOut io.Writer) error {
	if term := tmux.Term(); term != "" {
		fmt.Fprintf(out, "note: this box has no terminfo for TERM=%s; tmux is run as %s\n", os.Getenv("TERM"), term)
		os.Setenv("TERM", term)
	}
	// the open the live states are measured against
	state, now := filepath.Join(config.Home(), "state"), time.Now()
	if err := errors.Join(nextGeneration(state, name, now), writeSeat(state, name, []field{{"opened_at", seconds(now)}})); err != nil {
		fmt.Fprintf(errOut, "WARN could not record opening %s: %s\n", name, err)
	}
	return tmux.Attach(tmux.Own(), name)
}

// Rulebook is what a seat filed under no project opens on (config.seat_rulebook): ak's rules,
// then this host's own where it wrote any, each read as Python reads text.
func Rulebook() (string, error) {
	body, err := os.ReadFile(filepath.Join(config.Repo(), "orchestrator.md"))
	if err != nil {
		return "", err
	}
	local, err := os.ReadFile(filepath.Join(config.Home(), "rules.md"))
	if errors.Is(err, fs.ErrNotExist) {
		err = nil
	}
	text := string(body)
	if strings.TrimFunc(string(local), config.Space) != "" {
		text = strings.TrimRightFunc(text, config.Space) + "\n\n" + string(local)
	}
	return strings.NewReplacer("\r\n", "\n", "\r", "\n").Replace(text), err
}

// start is the seat's session on ak's server, as Python's orch.start opens it: its harness run
// by a launch file that removes itself, which no limit of tmux's on a command's length meets;
// the seat's name and its opener's state in its pane's environment and its session's; marked
// ak's, its pane named the harness's, and kept when the harness ends.
func start(state, name, cwd string, cmd []string) error {
	values, err := environment(name, tmux.Own())
	if err != nil {
		return err
	}
	shims, err := shims()
	if err != nil {
		return err
	}
	token := make([]byte, 4)
	rand.Read(token)
	launch := filepath.Join(state, "launch-"+name+"."+hex.EncodeToString(token))
	// new-session can set a variable, but not remove one the server holds
	script := "rm -f -- \"$0\"\n"
	if unset := slices.DeleteFunc(slices.Clone(values), func(f field) bool { return f.value != nil }); len(unset) > 0 {
		script += "unset"
		for _, f := range unset {
			script += " " + f.key
		}
		script += "\n"
	}
	if err := os.WriteFile(launch, []byte(script+"exec "+commandhelp.ShellJoin(cmd)+"\n"), 0o666); err != nil {
		return err
	}
	target := "=" + name + ":"
	args := slices.Concat(serverWide, []string{"new-session", "-d", "-s", name, "-c", cwd})
	for _, f := range values {
		value, _ := f.value.(string)
		args = append(args, "-e", tmux.Literal(f.key+"="+value))
	}
	args = append(args, commandhelp.ShellJoin([]string{"sh", launch}))
	// later panes and Ctrl-b m in the same home as the harness
	for _, f := range values {
		if value, set := f.value.(string); set {
			args = append(args, ";", "set-environment", "-t", target, f.key, tmux.Literal(value))
		} else {
			args = append(args, ";", "set-environment", "-t", target, "-r", f.key)
		}
	}
	args = append(args, ";", "set-option", "-t", target, tmux.Mark, "1", ";", "set-option", "-F", "-t", target, "@ak_harness_pane", "#{pane_id}",
		";", "set-option", "-t", target, "remain-on-exit", "on")
	if err := tmux.Spawn(tmux.Own(), shims+string(os.PathListSeparator)+os.Getenv("PATH"), args...); err != nil {
		os.Remove(launch)
		return fmt.Errorf("tmux could not start the session %s in %s: %v", name, cwd, err)
	}
	return nil
}

// environment is what a seat takes from whoever opens it, as Python's orch.seat_env: its home,
// its name and server, where its harnesses keep their state and where its pages go; and not the
// mark of the ak that opened it, which it outlives.  A nil value is one it goes without.
func environment(name, server string) ([]field, error) {
	values := []field{{"HOME", config.UserHome()}, {"AGENTKIT_SESSION", name}, {"AGENTKIT_TMUX_SOCKET", server}, {"AK_OWNER", nil}}
	names, err := config.StateEnv()
	for _, key := range slices.Compact(slices.Sorted(slices.Values(append(names, notify.EnvNames...)))) {
		if !slices.ContainsFunc(values, func(f field) bool { return f.key == key }) {
			var value any
			if set, ok := os.LookupEnv(key); ok {
				value = set
			}
			values = append(values, field{key, value})
		}
	}
	return values, err
}

// shims puts each of ak's shims, tools/<name>-shim, in ~/.agentkit/bin as <name>, as Python's
// guard.install_shim does: a link an older install left at a checkout since moved, or one at
// another tool, is pointed at this install's again.  Their folder.
func shims() (string, error) {
	dir := filepath.Join(config.Home(), "bin")
	if err := os.MkdirAll(dir, 0o777); err != nil {
		return "", err
	}
	for _, target := range config.Glob(filepath.Join(config.Repo(), "tools"), "*-shim") {
		name := strings.TrimSuffix(filepath.Base(target), "-shim")
		link := filepath.Join(dir, name)
		at, err := filepath.EvalSymlinks(link)
		if want, _ := filepath.EvalSymlinks(target); err == nil && at == want {
			continue
		}
		tmp := filepath.Join(dir, fmt.Sprintf(".%s.%d", name, os.Getpid()))
		if err := os.Symlink(target, tmp); err != nil {
			return "", err
		}
		if err := os.Rename(tmp, link); err != nil {
			return "", err
		}
	}
	return dir, nil
}

// unclaimed is whether nothing holds the name or the folder that Python's open takes over and
// Go does not yet: a file a gone seat left under the name, but the locks its writers wait on, or
// a checkout of the folder's own, whose git ak keeps from collecting.
func unclaimed(state, name, cwd string) bool {
	entries, err := os.ReadDir(state)
	if _, git := os.Lstat(filepath.Join(cwd, ".git")); err != nil || git == nil {
		return false
	}
	for _, entry := range entries {
		if owner, owned := config.SeatFileOwner(entry.Name()); owned && owner == name && !strings.HasSuffix(entry.Name(), ".lock") {
			return false
		}
	}
	return true
}

func modelList(names []string) []any {
	list := []any{}
	for _, name := range names {
		list = append(list, name)
	}
	return list
}
