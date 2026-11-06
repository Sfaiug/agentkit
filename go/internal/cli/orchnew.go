package cli

import (
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
	"agentkit/internal/seat"
	"agentkit/internal/tmux"
	"agentkit/internal/usage"
)

// orchNew answers a person's new seat, `ak orch [NAME] --model M [--workers W]`, as Python's
// orch.main, orch.select and orch.create do: the flags refused before anything is asked, the name
// and the workers asked where not given, a name tmux holds for no seat refused.  A preview
// (`--dry-run`) prints what the seat would take and the command it would run, its rulebook written
// into a scratch folder gone once that is printed, and saves and starts nothing; an open, from a
// person's terminal, opens the seat and hands it that terminal; a seat on a provider's accounts
// opens on the one its login and usage pick (seat.OpeningAccount).  The rest is Python's: a seat
// tmux or a record holds under the name, an open on a provider's accounts, and an open with no
// tmux, whose harness runs in the terminal itself.
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
	if err != nil || dryRun && seat.Project(cwd) != "" {
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
	reason := "--model"
	if orchestrator == "" {
		var ok bool
		orchestrator, reason, ok, err = askOrchestrator(out)
		if err != nil {
			return notImplemented(errOut, "orch")
		}
		if !ok {
			return 0
		}
		model, err = config.ModelNamed(orchestrator)
		if err != nil {
			return notImplemented(errOut, "orch")
		}
	}
	if accounts, err := config.Accounts(model.Provider); err != nil || len(accounts) > 0 && !dryRun {
		return notImplemented(errOut, "orch")
	}
	if crew == nil {
		asked, ok, err := askWorkers(out)
		if err != nil {
			return notImplemented(errOut, "orch")
		}
		if !ok {
			return 0
		}
		crew = asked
	}
	if !dryRun {
		opened, err := seat.Open(name, orchestrator, model, crew, cwd, unnamed)
		if !opened {
			return notImplemented(errOut, "orch")
		}
		if err == nil {
			err = seat.Attach(name, out, errOut)
		}
		if err == nil {
			return 0
		}
		fmt.Fprintf(errOut, "ak orch: %s\n", err)
		return 2
	}
	account, err := seat.OpeningAccount(orchestrator, model)
	if errors.Is(err, usage.ErrPython) {
		return notImplemented(errOut, "orch")
	} else if err != nil {
		fmt.Fprintf(errOut, "ak orch: %s\n", err)
		return 2
	}
	scratch, err := os.MkdirTemp("", "ak-dry-run-")
	defer os.RemoveAll(scratch)
	rulebook := filepath.Join(scratch, "rulebook-"+name+".md")
	if text, unread := seat.Rulebook(name); err != nil || unread != nil || os.WriteFile(rulebook, []byte(text), 0o666) != nil {
		return notImplemented(errOut, "orch")
	}
	cmd, _, ok := adapters.Fresh(model, append(os.Environ(), "AGENTKIT_SESSION="+name, "AGENTKIT_SEAT_REPO=",
		"AGENTKIT_RULEBOOK_DIR="+scratch, "AGENTKIT_RULEBOOK="+rulebook, "AGENTKIT_FIRST_PROMPT=", config.AccountEnv(account)))
	if !ok {
		return notImplemented(errOut, "orch")
	}
	fmt.Fprintf(out, "orch: %s (%s)\nsession %s in %s (new)\nworkers %s\n", orchestrator, reason, name, cwd, strings.Join(crew, " "))
	if tmux.Term() != "" {
		fmt.Fprint(out, "TERM=xterm-256color ")
	}
	fmt.Fprintln(out, commandhelp.ShellJoin(cmd))
	return 0
}

// held is whether Python attaches or reopens that name, whatever the flags: its seat tmux holds,
// or a file a seat's record or a rename's pointer keeps under it.
func held(name string) bool {
	path, err := config.SessionPath(name)
	if _, missing := os.Lstat(path); err != nil || !errors.Is(missing, fs.ErrNotExist) {
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
