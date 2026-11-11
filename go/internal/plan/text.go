package plan

import (
	"errors"
	"os"
	"unicode/utf8"

	"agentkit/internal/parsed"
)

// texts is what each plan holds, read again only once it changed (Python's plan.lines): every
// reader's, a string no reader can change.
var texts = parsed.Of(func(plan string) (string, error) {
	data, err := os.ReadFile(plan)
	if err == nil && !utf8.Valid(data) {
		err = errors.New("not UTF-8")
	}
	return string(data), err
})
