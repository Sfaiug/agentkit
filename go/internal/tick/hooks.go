package tick

import "agentkit/internal/tmux"

// hookOptions is the server hooks row (orch.set_hook_options): on ak's own server, which one started
// before them lacks, the options that run ak (tmux.Hooks) alone, since loading the whole conf again
// adds its terminal-features once more each time.  A server that is not up, holding no session,
// gets nothing, and a set that fails is the next tick's to try again.
func hookOptions() error {
	if len(tmux.Sessions(tmux.Own())) == 0 {
		return nil
	}
	hooks, err := tmux.Hooks()
	if err != nil {
		return errLeft
	}
	var lists [][]string
	for _, hook := range hooks {
		lists = append(lists, []string{"set-option", "-gq", hook[0], hook[1]})
	}
	tmux.Lists(tmux.Own(), lists)
	return nil
}
