package adapters

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
)

// run runs the program as a child on this terminal, which Windows cannot hand over, and answers
// its exit code; Ctrl+C is the program's, which shares the console, and what it shows passes through
// nothing here for moved to take word of.
func run(program string, words, env []string, errOut io.Writer, _ func()) int {
	cmd := exec.Command(program, words[1:]...)
	cmd.Args[0], cmd.Env = words[0], env
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	signal.Ignore(os.Interrupt)
	if err := cmd.Run(); cmd.ProcessState == nil {
		fmt.Fprintf(errOut, "ak adapter: %s: %s\n", words[0], err)
		return 126
	}
	return cmd.ProcessState.ExitCode()
}
