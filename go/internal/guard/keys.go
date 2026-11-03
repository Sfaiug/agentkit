package guard

import "agentkit/internal/tmux"

// Keys types those keys into a pane on ak's own server: the guard refuses these commands to
// anything else in a seat, so this is the one way Go's ak types, and its one typer is the
// hand-back's confirmed send under the seat's typing lock (seat.TypeAtPrompt).
func Keys(pane string, keys ...string) (string, error) {
	return tmux.Ask(tmux.Own(), append([]string{"send-keys", "-t", pane}, keys...)...)
}
