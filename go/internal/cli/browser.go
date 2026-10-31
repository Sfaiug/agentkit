package cli

import (
	"errors"
	"fmt"
	"io"

	"agentkit/internal/browser"
)

// `ak browser status`, `login` and `install` where Go reads the machine as Python does; the
// rest of each is Python's, before Go has printed anything.
func init() {
	for name, command := range map[string]func(io.Writer) (int, error){
		"status": browser.Status, "login": browser.Login, "install": browser.Install,
	} {
		commands["browser "+name] = func(_ []string, out, errOut io.Writer) int {
			code, err := command(out)
			if errors.Is(err, browser.ErrPython) {
				return notImplemented(errOut, "browser "+name)
			}
			if err != nil {
				fmt.Fprintf(errOut, "ak browser: %v\n", err)
				return 2
			}
			return code
		}
	}
}
