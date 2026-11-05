//go:build linux || darwin

package terminal

import "syscall"

// TakeKeys reads the same keys at a printed prompt, leaving the caller's screen up.
func (k *Keyboard) TakeKeys() { k.take(false) }

func (k *Keyboard) take(screen bool) {
	if k.taken || attrs(getAttrs, &k.saved) != nil {
		return
	}
	k.taken, k.screen = true, screen
	k.listen()
	raw := k.saved
	raw.Lflag &^= syscall.ICANON | syscall.ECHO
	raw.Cc[syscall.VMIN], raw.Cc[syscall.VTIME] = 1, 0
	attrs(setAttrs, &raw)
	if screen {
		syscall.Write(outFD, []byte(takeModes))
	}
}
