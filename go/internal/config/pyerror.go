package config

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"syscall"

	"agentkit/internal/commandhelp"
)

// PyError is err as Python's OSError says it: `[Errno 2] No such file or directory: 'a'`, with
// ` -> 'b'` after for a second path.
func PyError(err error) string {
	var errno syscall.Errno
	if !errors.As(err, &errno) {
		return err.Error()
	}
	text := errno.Error()
	said := fmt.Sprintf("[Errno %d] %s%s", int(errno), strings.ToUpper(text[:1]), text[1:])
	var link *os.LinkError
	var path *os.PathError
	switch {
	case errors.As(err, &link):
		said += ": " + commandhelp.Quote(link.Old) + " -> " + commandhelp.Quote(link.New)
	case errors.As(err, &path):
		said += ": " + commandhelp.Quote(path.Path)
	}
	return said
}
