package adapters

import (
	"fmt"
	"io"
	"os"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// Seat is Go's wrapper on a seat's line, `seat -- <words>`: it runs the harness's words in the
// seat's own terminal on the login $AGENTKIT_ACCOUNT names, so the terminal's size, what the
// harness prints, what is typed to it and its exit code are the seat's.  It answers the exit
// code where the harness never starts.
func Seat(name string, args []string, errOut io.Writer) int {
	login, ok, err := config.Account(name)
	if err != nil {
		fmt.Fprintf(errOut, "ak adapter: %s\n", err)
		return 2
	}
	env := os.Environ()
	if ok {
		env = login.Environ(env)
	}
	words, env := environ(args[min(len(args), 1):], env)
	if len(words) == 0 || args[0] != "--" {
		fmt.Fprintln(errOut, "usage: ak adapter <root> <harness> seat -- <harness words>")
		return 2
	}
	program := harness.Binary(words[0])
	if program == "" {
		fmt.Fprintf(errOut, "ak adapter: %s: not found\n", words[0])
		return 127
	}
	return run(program, words, env, errOut)
}
