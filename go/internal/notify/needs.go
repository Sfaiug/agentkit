package notify

import (
	"context"
	"io"
)

// Needs is ak's own question about a seat, Python's shaped with an event id: recorded beside the
// standing question, once for its event, then its existing card evaluated with shaped's zero
// wait on the word and last input.  False, recorded or not, where that card is Python's to evaluate.
func Needs(name, text, source string, published func(string) (string, any), errOut io.Writer) (bool, error) {
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
	return turnedQuestion(name, published, clock, 0, errOut)
}
