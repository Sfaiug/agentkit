package cli

import (
	"errors"
	"fmt"
	"io"

	"agentkit/internal/browser"
)

func init() { commands["browser status"] = browserStatus }

// browserStatus is `ak browser status` where Go reads the stack as Python does (browser.Status);
// the rest is Python's, before Go has printed anything.
func browserStatus(_ []string, out, errOut io.Writer) int {
	code, err := browser.Status(out)
	if errors.Is(err, browser.ErrPython) {
		return notImplemented(errOut, "browser status")
	}
	if err != nil {
		fmt.Fprintf(errOut, "ak browser: %v\n", err)
		return 2
	}
	return code
}
