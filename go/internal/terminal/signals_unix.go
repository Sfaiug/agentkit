//go:build linux || darwin

package terminal

import (
	"os/signal"
	"syscall"
)

// listen is resumed with the keyboard; Give leaves the process's signals to whoever has the terminal.
func (k *Keyboard) listen() {
	signal.Notify(k.heard, syscall.SIGTERM, syscall.SIGHUP, syscall.SIGQUIT, syscall.SIGINT, syscall.SIGTSTP, syscall.SIGWINCH)
}
