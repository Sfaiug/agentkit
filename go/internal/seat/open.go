package seat

import (
	"cmp"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/adapters"
	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/hooks"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// Open is the shared new-seat launch used by the menu and ak orch. Its rulebook precedes
// the adapter's command, and its record uses Python's locks and format. False leaves
// unsupported harness launches, provider accounts and leftover seat files to Python.
func Open(name, orchestrator string, model config.Model, workers []string, cwd string, unnamed bool, reviews ...[]string) (bool, error) {
	repo := Project(cwd)
	if repo != "" {
		cwd = repo
	}
	return open(name, orchestrator, model, workers, cwd, unnamed, repo, true, reviews...)
}

func open(name, orchestrator string, model config.Model, workers []string, cwd string, unnamed bool, repo string, remember bool, reviews ...[]string) (bool, error) {
	state := filepath.Join(config.Home(), "state")
	titled, known := harness.Opens(model.Harness)
	bound, unbound := config.Bind()
	models, err := config.Models()
	if !known || !opensAt(model) || !unclaimed(state, name) || unbound != nil || err != nil {
		return false, nil
	}
	// written before its adapter is asked, which may read it, and gone again where no seat comes
	// of it: unclaimed takes a file left under the name for a gone seat's
	rulebook := filepath.Join(state, "rulebook-"+name+".md")
	text, err := openingRulebook(name, repo)
	if unnamed {
		text = namingItself(text) // what its record will say, kept only once a seat comes of it
	}
	if err == nil {
		err = os.WriteFile(rulebook, []byte(text), 0o666)
	}
	if err != nil {
		os.Remove(rulebook)
		return true, fmt.Errorf("no rulebook for %s: %w", name, err)
	}
	created := seconds(time.Now())
	cmd, conversation, err := adapters.Command(model, append(os.Environ(), "AGENTKIT_SESSION="+name, "AGENTKIT_SEAT_REPO="+repo,
		"AGENTKIT_RULEBOOK="+rulebook, "AGENTKIT_FIRST_PROMPT="))
	if cmd == nil {
		os.Remove(rulebook)
		if err != nil {
			return true, fmt.Errorf("%s's %w", orchestrator, err)
		}
		return false, nil
	}
	fields := []field{{"orchestrator", orchestrator}, {"workers", modelList(workers)}}
	var reviewers []string
	for _, each := range bound.Reviewers {
		reviewers = append(reviewers, each.(string))
	}
	if len(reviews) > 0 {
		reviewers = reviews[0]
	}
	if reviewers != nil {
		fields = append(fields, field{"reviewers", modelList(reviewers)})
	}
	fields = append(fields, field{"cwd", cwd}, field{"repo", orNone(repo)}, field{"created", created}, field{"account", nil}, field{"home_account", nil})
	if unnamed {
		fields = append(fields, field{"unnamed", true})
	}
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
	if remember {
		config.RememberDefaults(orchestrator, workers, reviewers, func() error { // a seat is made all the same
			offered, err := config.Offered()
			if err != nil {
				return err
			}
			return keepEfforts(state, bound.Models, models, offered)
		})
	}
	if err := forgetSeen(state, name, time.Now()); err != nil {
		return true, err
	}
	// Relaunch also takes the repository before the seat lock.
	release, err := openingCheckout(cwd)
	if err != nil {
		return true, err
	}
	defer release()
	hooks.HandTaskTemplate()
	// under the seat's lock, as a rename going on keeps its record
	err = notify.Held(context.Background(), name, func(current string) error {
		var issued *run.Object
		var extra []string
		var preparing error
		// before the harness is up: its first prompt may be offered a newer rulebook already
		err := update(state, current, func(data *run.Object) bool {
			if issued, extra, preparing = harness.Launched(model.Harness, cwd, conversation, data.Copy()); preparing != nil {
				return false
			}
			for _, key := range issued.Keys() {
				fill(data, []field{{key, issued.Get(key)}})
			}
			data.Set("rulebook_sha", digest([]byte(text)))
			return true
		})
		if err = cmp.Or(err, preparing); err != nil {
			harness.Retire(model.Harness, issued)
			return err
		}
		if len(extra) > 0 {
			cmd = slices.Concat([]string{"env"}, extra, cmd)
		}
		// A fresh launch has begun no turn. Publish before starting it, so a hook can supersede
		// this baseline even when the caller opens a seat after the tick's health row.
		if err := writeSeat(state, current, []field{{"word", "idle"}}); err != nil {
			return err
		}
		if err := start(state, current, cwd, cmd); err != nil {
			// no harness read them
			harness.Retire(model.Harness, issued)
			update(state, current, func(data *run.Object) bool {
				for _, key := range append([]string{"resumable", "rulebook_sha"}, harness.RecordKeys(model.Harness)...) {
					data.Delete(key)
				}
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
// this process's place, or a client already on ak's server moved over.  With no terminal on both
// ends there is none to hand over, and saying where the seat is is the whole answer.  It answers
// only where it could not.
func Attach(name string, out, errOut io.Writer) error {
	return attachTerminal(name, out, errOut, tmux.Attach)
}

// sayWhere says how to reach the running seat, the whole answer with no terminal to hand over.
func sayWhere(name string, out io.Writer) error {
	program, err := exec.LookPath("tmux")
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "session %s is running; attach it with `%s`\n", name, commandhelp.ShellJoin([]string{program, "-L", tmux.Own(), "attach", "-t", name}))
	return nil
}

// start is the seat's session on ak's server, as Python's orch.start opens it: its harness run
// by a launch file that removes itself, which no limit of tmux's on a command's length meets;
// the seat's name and its opener's state in its pane's environment, then its session's; marked
// ak's, its pane named the harness's, and kept when the harness ends.
func start(state, name, cwd string, cmd []string) error {
	server := tmux.Own()
	values, err := environment(name, server)
	if err != nil {
		return err
	}
	shims, err := shims()
	if err != nil {
		return err
	}
	command, launch, err := launchFile(state, name, values, cmd)
	if err != nil {
		return err
	}
	target := "=" + name + ":"
	args := slices.Concat([]string{"new-session", "-d", "-s", name, "-c", cwd}, paneEnvironment(values), []string{command})
	if err := tmux.Spawn(server, shims+string(os.PathListSeparator)+os.Getenv("PATH"), args...); err != nil {
		os.Remove(launch)
		return fmt.Errorf("tmux could not start the session %s in %s: %v", name, cwd, err)
	}
	kept := append(keptEnvironment(target, values), ";", "set-option", "-t", target, tmux.Mark, "1", ";", "set-option", "-F", "-t", target, tmux.HarnessPane, "#{pane_id}",
		";", "set-option", "-t", target, "remain-on-exit", "on")
	if _, err := tmux.Ask(server, kept[1:]...); err != nil {
		return fmt.Errorf("cannot set up the session %s: %v", name, err)
	}
	return nil
}

// paneEnvironment is those values as the words that start a pane in them.
func paneEnvironment(values []field) []string {
	var args []string
	for _, f := range values {
		value, _ := f.value.(string)
		args = append(args, "-e", tmux.Literal(f.key+"="+value))
	}
	return args
}

// keptEnvironment is those values as commands, each after a `;`, for later panes and Ctrl-b m to
// start in the same home as the harness.
func keptEnvironment(target string, values []field) []string {
	var args []string
	for _, f := range values {
		if value, set := f.value.(string); set {
			args = append(args, ";", "set-environment", "-t", target, f.key, tmux.Literal(value))
		} else {
			args = append(args, ";", "set-environment", "-t", target, "-r", f.key)
		}
	}
	return args
}

// environment is what a seat takes from whoever opens it, as Python's orch.seat_env: its home,
// its name, where its harnesses keep their state and where its pages go; and not the mark of the
// ak that opened it, which it outlives.  A nil value is one it goes without.  It names its server
// only where its HOME would not: an ak opened in it under another HOME then reaches that HOME's
// own, never the seats'.
func environment(name, server string) ([]field, error) {
	var socket any
	if server != tmux.HomeServer() {
		socket = server
	}
	values := []field{{"HOME", config.UserHome()}, {"AGENTKIT_SESSION", name}, {"AGENTKIT_TMUX_SOCKET", socket}, {"AK_OWNER", nil}}
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

// unclaimed leaves files of a gone seat to Python, but not the locks its writers wait on.
func unclaimed(state, name string) bool {
	entries, err := os.ReadDir(state)
	if err != nil {
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
