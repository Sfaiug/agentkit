package tmux

import (
	"context"
	"time"
)

// Capture is what a pane shows as capture-pane prints it, untrimmed: a saved screen keeps its
// indentation and blank lines.
func Capture(bound time.Duration, server, pane string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), bound)
	defer cancel()
	out, err := asked(ctx, server, "capture-pane", "-p", "-t", pane)
	return string(out), err
}
