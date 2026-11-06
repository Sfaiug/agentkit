package adapters

import (
	"cmp"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// Fresh is the TUI command a seat of model opens on in a new conversation, on the login env's
// AGENTKIT_ACCOUNT names, as Python's orch.command and fresh_command build it: ak's own env words,
// then the line the harness's adapter prints for `interactive`, under a new conversation id or,
// where its TUI cannot be told one (exit 3), none; and that id, "" for none.  env is what the
// adapter is told.  No line where none opens: Python's launch says why where no adapter runs or it
// prints no line, and the error does, after the model's name, where a file the harness reads on
// its own, which nothing on the line can stop, is there.
func Fresh(model config.Model, env []string) ([]string, string, error) {
	conversation := uuid()
	line, told, err := command(model, env, []string{conversation, "new"}, nil)
	if !told {
		conversation = ""
	}
	return line, conversation, err
}

// Resumed is the command a seat of model comes back on with the conversation it owns, as Python's
// orch.resume_command builds it: resumed where its harness has opened it, else handed over as one
// to open, or resumed after all where its TUI cannot be told one.
func Resumed(model config.Model, conversation string, opened bool, env []string) ([]string, error) {
	if opened {
		line, _, err := command(model, env, []string{conversation}, nil)
		return line, err
	}
	line, _, err := command(model, env, []string{conversation, "new"}, []string{conversation})
	return line, err
}

// answering is what answers `interactive` for a harness: the script $AGENTKIT_ADAPTER_DIR holds;
// else this program, to which the stubs under go/adapters hand every verb, where the manifest
// gives it the words of a seat's line; else the shell adapter shipped beside the manifest, whose
// line is the one Python's launch runs.
func answering(name string) ([]string, error) {
	adapter, err := config.Adapter(name)
	if !errors.Is(err, config.ErrNoAdapterDir) {
		return []string{adapter}, err
	}
	launch, err := config.Section(name, "launch")
	if err != nil {
		return nil, err
	}
	if launch["seat"] == nil && harness.Interactive(name) == nil {
		return []string{filepath.Join(config.Repo(), "adapters", name+".sh")}, nil
	}
	self, _ := os.Executable()
	self, err = filepath.EvalSymlinks(self)
	return []string{self, "adapter", filepath.Dir(filepath.Dir(self)), name}, err
}

// command is the seat's line from the adapter's answer to `interactive` with first, whether that
// answered, or with then where first, naming a conversation to open, exits 3: none is told one.
// No line and no error where the adapter gives none.
func command(model config.Model, env []string, first, then []string) ([]string, bool, error) {
	argv, err := answering(model.Harness)
	if err != nil {
		return nil, false, nil
	}
	account := commandAccount(env)
	env = append(slices.Clip(env), "AGENTKIT_ACCOUNT="+account)
	args := []string{"interactive", model.ID, model.Efforts["effort"]}
	ask := func(words []string) ([]byte, error) {
		run := exec.Command(argv[0], slices.Concat(argv[1:], args, words)...)
		run.Env = env
		return run.Output()
	}
	out, err := ask(first)
	asFirst := true
	if exit := (*exec.ExitError)(nil); errors.As(err, &exit) && exit.ExitCode() == 3 && first[len(first)-1] == "new" {
		out, err = ask(then)
		asFirst = false
	}
	line, ok := commandhelp.ShellSplit(strings.TrimFunc(string(out), config.Space))
	if err != nil || !ok || len(line) == 0 {
		return nil, false, nil
	}
	// ak's editor is the seat's own, so the owner's unsent text can be set aside for a line of
	// ak's (agentkit/aside_editor.py); the owner's own goes beside it
	editor := filepath.Join(config.Repo(), "tools", "aside-editor")
	owner, set := os.LookupEnv("AK_OWNER_EDITOR")
	if !set {
		owner = cmp.Or(os.Getenv("VISUAL"), os.Getenv("EDITOR"))
	}
	line = append([]string{"env", "AGENTKIT_ACCOUNT=" + account, "VISUAL=" + editor, "EDITOR=" + editor, "AK_OWNER_EDITOR=" + owner}, line...)
	// looked for as the line sets the harness's home, and, on the usual login, in the usual homes
	// too, where an adapter drops an account's home a seat handed down (config.unswitched_files)
	_, seated := environ(line, os.Environ())
	values := map[string]string{}
	for _, pair := range seated {
		key, value, _ := strings.Cut(pair, "=")
		values[key] = value
	}
	cwd, _ := os.Getwd()
	for _, path := range config.Unswitched(model.Harness, values, cwd) {
		if _, err := os.Stat(path); err == nil {
			return nil, false, fmt.Errorf("harness reads %s on its own and has no switch for it, so a seat on it would "+
				"take instructions beside its rulebook: move it away, or open the seat on a model of another harness", path)
		}
	}
	return line, asFirst, nil
}
