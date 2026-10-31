//go:build unix

package adapters

import (
	"fmt"
	"io"
	"syscall"
)

// run replaces this process with the program, so nothing stands between it and the terminal.
func run(program string, words, env []string, errOut io.Writer) int {
	err := syscall.Exec(program, words, env)
	fmt.Fprintf(errOut, "ak adapter: %s: %s\n", words[0], err)
	return 126
}
