package plan

import (
	"context"

	"agentkit/internal/notify"
)

// Delivered checks the lines a merge delivered, only its own check for a fix run. A fix
// that did not prove its line leaves that line for the seat to build.
func Delivered(ctx context.Context, name, check string) error {
	err := verifying(ctx, name, func() error { return verify(ctx, name, check) })
	if check == "" {
		return err
	}
	return notify.Held(ctx, name, func(current string) error {
		lines, readErr := read(current)
		if readErr != nil {
			return readErr
		}
		changed := false
		for i, text := range lines {
			line, ok := parse(text)
			if !ok || line.Check != check || !line.Deferred || line.proven() {
				continue
			}
			if held, err := taken(current, line, followupOpen); held || err != nil {
				continue
			}
			lines[i] = added(line.What, line.Check, line.Project, line.When, line.Base).ticked("")
			changed = true
		}
		if changed {
			return write(current, lines)
		}
		return err
	})
}
