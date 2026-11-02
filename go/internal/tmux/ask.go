package tmux

import (
	"context"
	"strings"
	"time"
)

// Ask is what one server answers a command, stripped as Python's orch.tmux_out strips it; an
// error where tmux refused, is missing or never answered.
func Ask(server string, args ...string) (string, error) {
	return AskWithin(ceiling, server, args...)
}

// AskWithin is Ask for a caller that waits no longer than that.
func AskWithin(bound time.Duration, server string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), bound)
	defer cancel()
	out, err := command(ctx, server, args...).Output()
	return strings.TrimSpace(string(out)), err
}
