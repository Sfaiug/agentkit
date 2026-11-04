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
	if n <= 0 || n > 9 || n*10 > count {
		return first
	}
	until := time.Now().Add(500 * time.Millisecond)
	for time.Now().Before(until) {
		next, got := k.next(time.Until(until))
		if !got {
			break
		}
		raw := []byte{next}
		key, _, ok := spell(next, func(within time.Duration) (byte, bool) {
			next, got := k.next(min(within, time.Until(until)))
			if got {
				raw = append(raw, next)
			}
			return next, got
		})
		if !ok || key.Name == "pointer" && key.Mouse.Button&32 != 0 && key.Mouse.Button&64 == 0 {
			continue
		}
		if key.Name == "char" && len(key.Char) == 1 && key.Char[0] >= '0' && key.Char[0] <= '9' {
			return first + key.Char
		}
		k.keyed = append(raw, k.keyed...)
		break
	}
	return first
}
