package cli

import (
	"errors"
	"fmt"
	"io"

	"agentkit/internal/handin"
)

// init answers `hand-in` and each of its words, which Main takes off the arguments.
func init() {
	commands["hand-in"] = handIn
	for _, word := range []string{"finding", "follow-up", "dispute", "done", "blocked", "not-needed"} {
		commands["hand-in "+word] = func(args []string, out, errOut io.Writer) int {
			return handIn(append([]string{word}, args...), out, errOut)
		}
	}
}

// handIn hands in what args say to the worker turn, or says why not.
func handIn(args []string, _, errOut io.Writer) int {
	err := handin.Hand(args)
	if errors.Is(err, handin.ErrPython) {
		return notImplemented(errOut, "hand-in")
	} else if err != nil {
		fmt.Fprintf(errOut, "ak hand-in: %s\n", err)
		return 2
	}
	return 0
}
