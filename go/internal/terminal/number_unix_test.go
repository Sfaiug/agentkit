//go:build linux || darwin

package terminal

import "testing"

func TestNumberWaitsAcrossCompletePointerReports(t *testing.T) {
	for _, sent := range []string{
		"\x1b[<35;80;20M2x",
		"\x1b[<32;80;20M\x1b[<35;80;21M2x",
		"\x1b]11;rgb:0000/0000/0000\x07\x1b[<35;80;20M2x",
	} {
		keyboard := &Keyboard{keyed: []byte(sent)}
		if got := keyboard.Number("1", 13); got != "12" || string(keyboard.keyed) != "x" {
			t.Errorf("%q: number %s, remaining %q", sent, got, keyboard.keyed)
		}
	}
}

func TestNumberRetainsOtherCompleteKeysAfterMotion(t *testing.T) {
	for _, sent := range []string{"\x1b[A", "\x1b[<0;8;10m", "\x1bx", "é", "\r"} {
		keyboard := &Keyboard{keyed: []byte("\x1b[<35;80;20M" + sent + "z")}
		if got := keyboard.Number("1", 13); got != "1" || string(keyboard.keyed) != sent+"z" {
			t.Errorf("%q: number %s, remaining %q", sent, got, keyboard.keyed)
		}
	}
	keyboard := &Keyboard{keyed: []byte("9")}
	if got := keyboard.Number("9", 13); got != "9" || string(keyboard.keyed) != "9" {
		t.Fatal("an unambiguous digit consumed the seat's next key")
	}
}
