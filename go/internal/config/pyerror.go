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
	said := fmt.Sprintf("[Errno %d] %s", int(errno), Strerror(errno))
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

// Strerror is err as Python's OSError.strerror says it, PyError without its number and path:
// `No such file or directory`.
func Strerror(err error) string {
	var errno syscall.Errno
	if !errors.As(err, &errno) {
		return err.Error()
	}
	text := errno.Error()
	return strings.ToUpper(text[:1]) + text[1:]
}
