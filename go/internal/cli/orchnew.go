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
)

// orchPreview answers a person's preview of a new seat naming both its models, `ak orch NAME
// --dry-run --model M --workers W`, as Python's orch.main and orch.create do with dry_run: what
// the seat would take and the command it would run, its rulebook written into a scratch folder
// gone once that is printed, and nothing saved or started.  The rest is Python's: a seat it would
// ask about, a name held, a seat filed under a project, and one on a provider's accounts, which
// opens on the one its login and usage pick.
func orchPreview(name string, flags map[string]string, out, errOut io.Writer) int {
	orchestrator := flags["--model"]
	workers, listed := flags["--workers"]
	cwd, err := os.Getwd()
	cwd = config.Resolve(cwd)
	if name == "" || orchestrator == "" || !listed || held(name) || err != nil || seat.Project(cwd) != "" {
		return notImplemented(errOut, "orch")
	}
	model, crew, err := picked(orchestrator, workers)
	if err != nil {
		fmt.Fprintf(errOut, "ak orch: %s\n", err)
		return 2
	}
	if accounts, err := config.Accounts(model.Provider); err != nil || len(accounts) > 0 {
		return notImplemented(errOut, "orch")
	}
	scratch, err := os.MkdirTemp("", "ak-dry-run-")
	defer os.RemoveAll(scratch)
	rulebook := filepath.Join(scratch, "rulebook-"+name+".md")
	if text, unread := rules(); err != nil || unread != nil || os.WriteFile(rulebook, []byte(text), 0o666) != nil {
		return notImplemented(errOut, "orch")
	}
	cmd, ok := adapters.Command(model, append(os.Environ(), "AGENTKIT_SESSION="+name, "AGENTKIT_SEAT_REPO=",
		"AGENTKIT_RULEBOOK_DIR="+scratch, "AGENTKIT_RULEBOOK="+rulebook, "AGENTKIT_FIRST_PROMPT="))
	if !ok {
		return notImplemented(errOut, "orch")
	}
	fmt.Fprintf(out, "orch: %s (--model)\nsession %s in %s (new)\nworkers %s\n", orchestrator, name, cwd, strings.Join(crew, " "))
	// tmux refuses a terminal it cannot describe, so a seat's tmux runs as xterm-256color where
	// infocmp knows no $TERM (orch.fix_term)
	if term := os.Getenv("TERM"); term != "" && term != "xterm-256color" && exec.Command("infocmp", term).Run() != nil {
		fmt.Fprint(out, "TERM=xterm-256color ")
	}
	fmt.Fprintln(out, commandhelp.ShellJoin(cmd))
	return 0
}

// held is whether something Python's open reads holds the name: a seat's file, its record or a
// rename's pointer, or a session on ak's tmux server, or a seat on the person's own.
func held(name string) bool {
	path, err := config.SessionPath(name)
	if _, missing := os.Lstat(path); err != nil || !errors.Is(missing, fs.ErrNotExist) {
		return true
	}
	for _, server := range []string{tmux.Own(), tmux.Default} {
		for _, session := range tmux.Sessions(server) {
			if config.Fold(session.Name) == name && (server != tmux.Default || session.Mark == "1") {
				return true
			}
		}
	}
	return false
}

// picked is the seat's orchestrator and workers as Python's select reads the flags, or why the
// config refuses them.
func picked(orchestrator, workers string) (config.Model, []string, error) {
	model, err := config.ModelNamed(orchestrator)
	if err != nil {
		return model, nil, err
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

// rules is the rulebook a seat filed under no project opens on (config.seat_rulebook): ak's
// rules, then this host's own where it wrote any, each read as Python reads text.
func rules() (string, error) {
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
