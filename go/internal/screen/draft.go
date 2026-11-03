package screen

import (
	"strings"

	"agentkit/internal/config"
)

// ComposerDraft is the composer's whole text without whitespace, "" when empty, false where none is
// found (watch.composer_draft).
func (r *Rules) ComposerDraft(pane string) (string, bool) {
	rows, found := r.composerRows(pane)
	return Unspaced(strings.Join(rows, "")), found
}

// Unspaced is text with no whitespace in it, as a composer's wrapping leaves it comparable.
func Unspaced(text string) string {
	return strings.Join(strings.FieldsFunc(text, config.Space), "")
}
