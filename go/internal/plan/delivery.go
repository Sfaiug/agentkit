package plan

import (
	"context"
	"errors"

	"agentkit/internal/notify"
)

// Delivered checks the lines a merge delivered.  A fix run checks its own line alone, waiting for
// whoever verifies, since that line's deferred mark is settled from its check's result; a fix that
// did not prove its line leaves that line for the seat to build.  Any other delivery never waits:
// it counts itself owed a verification begun after it, which runs here where none runs, and which
// the one verifying runs once it lets go (`settle`).  Delivered runs once waited in their endings,
// their follow-ups not handed on: 14 behind one verification of 81 lines (6 Nov 2026).
func Delivered(ctx context.Context, name, check string) error {
	if check == "" {
		if err := notify.Held(ctx, name, func(current string) error { return owe(current, 1) }); err != nil {
			return err
		}
		return settle(ctx, name, nil)
	}
	err := verifying(ctx, name, true, func() error {
		_, err := verify(ctx, name, check, nil)
		return err
	})
	err = notify.Held(ctx, name, func(current string) error {
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
	return errors.Join(err, settle(ctx, name, nil))
}
