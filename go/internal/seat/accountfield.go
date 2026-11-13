package seat

import "errors"

// errFieldHeld is a move off an account that waits: the respawn would end what the seat's input
// field holds, and it is not read whole and empty (watch.field_empty).
var errFieldHeld = errors.New("input field not read empty")

// fieldEmpty is watch.field_empty: that capture's input field, read whole, holds nothing.  A
// screen's rules can read a tall draft as an empty prompt; the composer read whole cannot.
func fieldEmpty(own, pane string) bool {
	held, drawn := eyeOf(own).rules.ComposerDraft(pane)
	return drawn && held == ""
}
