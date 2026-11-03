//go:build linux || darwin

package terminal

import (
	"strconv"
	"time"
)

// Number waits for a second digit only where some seat's number could start with first.
// A non-digit read early stays with the menu; otherwise the seat owns the following keys.
func (k *Keyboard) Number(first string, count int) string {
	n, _ := strconv.Atoi(first)
	if n > 0 && n <= 9 && n*10 <= count {
		if next, got := k.next(500 * time.Millisecond); got {
			if next >= '0' && next <= '9' {
				return first + string(next)
			}
			k.keyed = append([]byte{next}, k.keyed...)
		}
	}
	return first
}
