package adapters

import (
	"cmp"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

// Command is the TUI command a new seat of model opens on the usual login, as Python's
// orch.command and fresh_command build it: ak's own env words, then the line the harness's
// adapter prints for `interactive`, under a new conversation id or, where its TUI cannot be told
// one (exit 3), none; and that id, "" for none.  The adapter is the script $AGENTKIT_ADAPTER_DIR
// holds, else this program, to which the stubs under go/adapters hand every verb.  env is what
// the adapter is told.  False where Python's launch says why none opens: no adapter runs, it
// prints no line, or a file the harness reads on its own, which nothing on the line can stop, is
// there.
func Command(model config.Model, env []string) ([]string, string, bool) {
	adapter, err := config.Adapter(model.Harness)
	argv := []string{adapter}
	if errors.Is(err, config.ErrNoAdapterDir) {
		self, _ := os.Executable()
		self, err = filepath.EvalSymlinks(self)
		argv = []string{self, "adapter", filepath.Dir(filepath.Dir(self)), model.Harness}
	}
	if err != nil {
		return nil, "", false
	}
	env = append(slices.Clip(env), "AGENTKIT_ACCOUNT=")
	args := []string{"interactive", model.ID, model.Efforts["effort"]}
	conversation := uuid()
	line, ok := []string(nil), false
	for _, call := range [][]string{append(args, conversation, "new"), args} {
		run := exec.Command(argv[0], slices.Concat(argv[1:], call)...)
		run.Env = env
		out, err := run.Output()
		if exit := (*exec.ExitError)(nil); len(call) > len(args) && errors.As(err, &exit) && exit.ExitCode() == 3 {
			conversation = ""
			continue
		}
		if line, ok = commandhelp.ShellSplit(strings.TrimFunc(string(out), config.Space)); err != nil || !ok || len(line) == 0 {
			return nil, "", false
		}
		break
	}
	// ak's editor is the seat's own, so the owner's unsent text can be set aside for a line of
	// ak's (agentkit/aside_editor.py); the owner's own goes beside it
	editor := filepath.Join(config.Repo(), "tools", "aside-editor")
	owner, set := os.LookupEnv("AK_OWNER_EDITOR")
	if !set {
		owner = cmp.Or(os.Getenv("VISUAL"), os.Getenv("EDITOR"))
	}
	line = append([]string{"env", "AGENTKIT_ACCOUNT=", "VISUAL=" + editor, "EDITOR=" + editor, "AK_OWNER_EDITOR=" + owner}, line...)
	// looked for as the line sets the harness's home, and, on the usual login, in the usual homes
	// too, where an adapter drops an account's home a seat handed down (config.unswitched_files)
	_, seated := environ(line, os.Environ())
	values := map[string]string{}
	for _, pair := range seated {
		key, value, _ := strings.Cut(pair, "=")
		values[key] = value
	}
	for _, path := range config.Unswitched(model.Harness, values) {
		if _, err := os.Stat(path); err == nil {
			return nil, "", false
		}
	}
	return line, conversation, true
}
