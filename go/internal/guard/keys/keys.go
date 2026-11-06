// Package keys is the one way Go's ak types into a pane: the guard refuses these commands to
// anything else in a seat, and its one typer is the hand-back's confirmed send under the seat's
// typing lock (seat.TypeAtPrompt).  It stands apart from the guard, which asks the seat package
// which project a checkout is, so the seat that types never imports the guard that asks it.
package keys

import "agentkit/internal/tmux"

// Type types those keys into a pane on ak's own server.
func Type(pane string, keys ...string) (string, error) {
	return tmux.Ask(tmux.Own(), append([]string{"send-keys", "-t", pane}, keys...)...)
}
