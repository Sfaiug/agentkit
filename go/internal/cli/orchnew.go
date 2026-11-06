package cli

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/adapters"
	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/tmux"
	"agentkit/internal/usage"
)

// orchNew answers a person's new seat, `ak orch [NAME] --model M [--workers W]`, as Python's
// orch.main, orch.select and orch.create do: the flags refused before anything is asked, the name
// asked where not given, a name tmux holds for no seat refused, then the orchestrator usage picks
// (chosen) and the workers asked where not given.  A preview (`--dry-run`) prints what the seat
// would take and the command it would run, its rulebook written into a scratch folder gone once
// that is printed, and saves and starts nothing; an open, from a person's terminal, opens the seat
// and hands it that terminal; either is filed under the project of the checkout it is made in.  A
// seat on a provider's accounts opens on the one its login and usage pick (seat.OpeningAccount).
// The rest is Python's, settled before usage is read: a name held (held), an open with no tmux,
// whose harness runs in the terminal itself, and a seat on a model Go does not carry
// (seat.Carried), any the question may pick, an open on a gone seat's name among them.  Past that
// read, whatever fails is an error.
func orchNew(name string, flags map[string]string, dryRun bool, out, errOut io.Writer) int {
	if name != "" && held(name) {
		return notImplemented(errOut, "orch")
	}
	orchestrator := flags["--model"]
	workers, listed := flags["--workers"]
	model, crew, err := picked(orchestrator, workers, listed)
	if err != nil {
		fmt.Fprintf(errOut, "ak orch: %s\n", err)
		return 2
	}
	cwd, err := os.Getwd()
	cwd = config.Resolve(cwd)
	if err != nil {
		return notImplemented(errOut, "orch")
	}
	if _, err := exec.LookPath("tmux"); err != nil && !dryRun {
		return notImplemented(errOut, "orch")
	}
	unnamed := false
	if name == "" {
		typed, ok, code := askName(out, errOut)
		if !ok {
			return code
		}
		name, unnamed = typed, typed == ""
		if unnamed {
			if name, ok = characterName(seat.ReadNames().Taken); !ok {
				return notImplemented(errOut, "orch")
			}
		}
	}
	if seat.ReadNames().Held(name) {
		fmt.Fprintf(errOut, "ak orch: tmux already holds a session named %s, and it is no seat; pick another name\n", commandhelp.Quote(name))
		return 2
	}
	failed := func(err error) int {
		fmt.Fprintf(errOut, "ak orch: %s\n", err)
		return 2
	}
	// the models the seat may open on: the one asked for, else any the question may pick
	choices, fallback := []string{orchestrator}, ""
	if orchestrator == "" {
		var unread error
		choices, err = config.Offered()
		fallback, unread = config.DefaultOrchestrator()
		if err = cmp.Or(err, unread); err != nil {
			return failed(err)
		}
	}
	for _, each := range choices {
		if model, err := config.ModelNamed(each); err != nil || !seat.Carried(name, model, dryRun) {
			return notImplemented(errOut, "orch")
		}
	}
	var text, repo string // a preview's rulebook and project, as an open's are read where it opens
	if dryRun {
		if repo = seat.Project(cwd); repo != "" {
			cwd = repo // where seat.Open runs it
		}
		if text, err = seat.PreviewRulebook(name, repo); err != nil {
			return notImplemented(errOut, "orch")
		}
	}
	reason := "--model"
	if orchestrator == "" {
		readings, err := usage.Collected()
		if err != nil {
			return failed(err)
		}
		picked, why, suffix := chosen(readings, choices, fallback)
		var ok bool
		if orchestrator, ok = askOrchestrator(out, choices, picked, suffix); !ok {
			return 0
		}
		if reason = why; orchestrator != picked {
			reason = "selected"
		}
		if model, err = config.ModelNamed(orchestrator); err != nil {
			return failed(err)
		}
	}
	if crew == nil {
		asked, ok, err := askWorkers(out)
		if err != nil {
			return failed(err)
		}
		if !ok {
			return 0
		}
		crew = asked
	}
	if !dryRun {
		models, _ := config.Models() // the config's, which Carried has read
		opened, err := seat.Open(name, orchestrator, models, crew, cwd, unnamed)
		if !opened { // settled above: config.toml or the state folder changed since
			err = fmt.Errorf("%s changed as the seat opened; open it again", config.Home())
		}
		if err == nil {
			err = seat.Attach(name, out, errOut)
		}
		if err == nil {
			return 0
		}
		return failed(err)
	}
	account, err := seat.OpeningAccount(orchestrator, model)
	if err != nil {
		return failed(err)
	}
	scratch, err := os.MkdirTemp("", "ak-dry-run-")
	if err != nil {
		return failed(err)
	}
	defer os.RemoveAll(scratch)
	rulebook := filepath.Join(scratch, "rulebook-"+name+".md")
	if err := os.WriteFile(rulebook, []byte(text), 0o666); err != nil {
		return failed(err)
	}
	cmd, _, err := adapters.Fresh(orchestrator, model, append(os.Environ(), "AGENTKIT_SESSION="+name, "AGENTKIT_SEAT_REPO="+repo,
		"AGENTKIT_RULEBOOK_DIR="+scratch, "AGENTKIT_RULEBOOK="+rulebook, "AGENTKIT_FIRST_PROMPT=", config.AccountEnv(account)), cwd)
	if err != nil {
		return failed(err)
	}
	fmt.Fprintf(out, "orch: %s (%s)\nsession %s in %s (new)\nworkers %s\n", orchestrator, reason, name, cwd, strings.Join(crew, " "))
	if tmux.Term() != "" {
		fmt.Fprint(out, "TERM=xterm-256color ")
	}
	fmt.Fprintln(out, commandhelp.ShellJoin(cmd))
	return 0
}

// held is whether the name is Python's to answer whatever the flags: its seat tmux holds, or a
// file under it that is no gone seat's record, a rename's pointer or one that will not read.  A
// gone seat's record is a name a seat opened with --model or --workers takes, as Python's create
// takes it; orchAgain reopens it where neither is given.
func held(name string) bool {
	path, err := config.SessionPath(name)
	if err != nil {
		return true
	}
	if record, err := run.ReadJSON(path); record == nil && !errors.Is(err, fs.ErrNotExist) || record != nil && record.Has(config.Renamed) {
		return true
	}
	return seat.ReadNames().Seat(name)
}

// picked is the seat's orchestrator and workers as Python's select reads the flags, or why the
// config refuses them: the one home of a model's choosing, for a preview and an open alike.  Workers
// not listed are nil, for the question.
func picked(orchestrator, workers string, listed bool) (config.Model, []string, error) {
	var model config.Model
	if orchestrator != "" {
		var err error
		if model, err = config.ModelNamed(orchestrator); err != nil {
			return model, nil, err
		}
	}
	if !listed {
		return model, nil, nil
	}
	names := strings.Split(workers, ",")
	for i, each := range names {
		if names[i] = strings.TrimFunc(each, config.Space); names[i] == "" {
			return model, nil, errors.New("--workers needs a comma-separated list of model names")
		}
	}
	for _, each := range names {
		if _, err := config.ModelNamed(each); err != nil {
			return model, nil, err
		}
	}
	if len(slices.Compact(slices.Sorted(slices.Values(names)))) < len(names) {
		return model, nil, errors.New("--workers contains duplicate model names")
	}
	return model, names, nil
}
