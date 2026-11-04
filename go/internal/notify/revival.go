package notify

import (
	"context"
	"io"
)

// RevivalFailed records the recovery event as shaped does, beside the standing question,
// then lets the seat's existing card and outbox decide whether a page is still owed.
func RevivalFailed(name, text, source string, published func(string) (string, any), errOut io.Writer) (bool, error) {
	if Suppressed(false, errOut) {
		return true, nil
	}
	known := true
	err := Held(context.Background(), name, func(current string) error {
		previous := Last(current)
		if previous != nil && previous.Str("source") == source {
			return nil
		}
		notice, read := said(current, []Kept{{Text: text}}, previous, false)
		if !read {
			known = false
			return nil
		}
		notice.Set("source", source)
		return writeNotice(current, notice)
	})
	if err != nil || !known {
		return known, err
	}
	return TurnedQuestion(name, published, errOut)
}
