package seat

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/hooks"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// relaunch is the common rulebook, adapter command and launch for Reopen and ReopenPast.
func (seat reopening) relaunch(dry bool, out io.Writer) (string, bool, error) {
	name, state := seat.name, filepath.Join(config.Home(), "state")
	text, err := Rulebook(name)
	if err != nil {
		return "", false, nil
	}
	// A dry adapter may write beside its rulebook, never into the real seat's files.
	dir, told := state, []string(nil)
	if dry {
		if dir, err = os.MkdirTemp("", "ak-dry-run-"); err != nil {
			return "", false, nil
		}
		defer os.RemoveAll(dir)
		told = []string{"AGENTKIT_RULEBOOK_DIR=" + dir}
	}
	// The harness opens with its rules or not at all. They are written before the launch decides,
	// as Python's resume_command writes them: a launch declined later, for a draft typed
	// meanwhile, leaves them newer than what the harness still running read, which its next
	// prompt is offered as a change, and `launch` puts the seat's record back, so nothing claims
	// that harness read them. Taking the file back instead would race a reopen writing it.
	rulebook := filepath.Join(dir, "rulebook-"+name+".md")
	if err = os.MkdirAll(dir, 0o777); err == nil {
		err = os.WriteFile(rulebook, []byte(text), 0o666)
	}
	if err != nil {
		return "", true, Refusal(fmt.Sprintf("no rulebook for %s: %v", name, err))
	}
	cmd, conversation, ok := seat.command(append(told, "AGENTKIT_RULEBOOK="+rulebook))
	if !ok {
		return "", false, nil
	}
	fmt.Fprintln(out, seat.said())
	if dry {
		fmt.Fprintln(out, commandhelp.ShellJoin(cmd))
		return name, true, nil
	}
	if dirs := dirsOf(seat.cwd); dirs.known {
		g := gitcall.Git{Repo: seat.cwd, Env: gitcall.ProjectEnv(seat.cwd)}
		held, err := lock.Shared(dirs.common)
		if err != nil {
			return "", true, err
		}
		defer held.Close()
		if err := g.NoAutoGC(); err != nil {
			return "", true, err
		}
	}
	hooks.HandTaskTemplate()
	settled, err := seat.launch(state, rulebook, cmd, conversation)
	if err != nil {
		return settled, true, err
	}
	// seen by whoever it is reopened for, as Python's resume stamps a seat it hands over; the
	// tick's reopening of a seat cut off mid-question launches it unseen (revival)
	return settled, true, update(state, settled, func(data *run.Object) bool {
		data.Set("seen", int(time.Now().Unix()))
		return true
	})
}
