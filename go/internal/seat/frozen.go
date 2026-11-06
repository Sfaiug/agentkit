package seat

import (
	"slices"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/tmux"
)

const frozenOption = "@ak_frozen"

type frozenPane struct{ target string }

// freezePane keeps the old harness from accepting input after its final look. The server
// restores input after ten seconds even if ak dies, and removes the respawn's guard with it.
func freezePane(name string) (*frozenPane, error) {
	frozen := &frozenPane{harnessPane(name)}
	thaw := frozen.release()
	later := commandhelp.ShellJoin(thaw[:5]) + " ; " + commandhelp.ShellJoin(thaw[6:])
	_, err := tmux.AskWithin(5*time.Second, tmux.Own(), "set-option", "-p", "-t", frozen.target, frozenOption, "1", ";",
		"select-pane", "-d", "-t", frozen.target, ";", "run-shell", "-b", "-d", "10", "-C", later)
	if err != nil {
		frozen.thaw()
		return nil, err
	}
	return frozen, nil
}

func (frozen *frozenPane) release() []string {
	return []string{"set-option", "-pu", "-t", frozen.target, frozenOption, ";", "select-pane", "-e", "-t", frozen.target}
}

func (frozen *frozenPane) thaw() {
	if frozen != nil {
		tmux.AskWithin(5*time.Second, tmux.Own(), frozen.release()...)
	}
}

func (frozen *frozenPane) guarded(args []string) []string {
	if frozen == nil {
		return args
	}
	return slices.Concat([]string{"show-options", "-pv", "-t", frozen.target, frozenOption, ";"}, args, []string{";"}, frozen.release())
}
