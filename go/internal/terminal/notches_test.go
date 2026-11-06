//go:build linux || darwin

package terminal

import (
	"strings"
	"testing"
)

// Wheel reports sent together are one key as far as they go, and the key after them is the next
// read's; reports that cancel out are none.
func TestASwipeIsOneKeyAndTheKeyAfterItTheNext(t *testing.T) {
	down, up, side := "\x1b[<65;10;10M", "\x1b[<64;10;10M", "\x1b[<66;10;10M"
	for sent, want := range map[string]int{
		strings.Repeat(down, 300) + "k": 300,
		down + up + up + side + "k":     -1,
		down + up + side + "k":          0,
	} {
		keyboard := &Keyboard{keyed: []byte(sent)}
		if want != 0 {
			if got := keyboard.ReadKey(); got.Name != "pointer" || got.Mouse.Notches != want {
				t.Errorf("%d notches read as %+v", want, got)
			}
		}
		if got := keyboard.ReadKey(); got.Name != "char" || got.Char != "k" {
			t.Errorf("after %d notches: %+v", want, got)
		}
	}
}
