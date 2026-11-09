package terminal

import "testing"

// A failed run's bar on `Limits` is drawn in FAIL's colour as Python's STATE_STYLES and LIGHT hold
// it: the strings Python's share_line writes on a dark and a light background and in eight colours.
func TestAFailedBarIsDrawnInFailsColour(t *testing.T) {
	for _, each := range []struct {
		screen Screen
		want   string
	}{
		{Screen{depth: 24}, "\x1b[38;2;122;70;84m━\x1b[0m\x1b[38;2;243;139;168m━\x1b[0m"},
		{Screen{depth: 24, light: true}, "\x1b[38;2;232;135;156m━\x1b[0m\x1b[38;2;210;15;57m━\x1b[0m"},
		{Screen{depth: 8}, "\x1b[31m━━\x1b[0m"},
	} {
		if got := each.screen.ShareLine(1, 2, "FAIL"); got != each.want {
			t.Errorf("%+v: %q, want %q", each.screen, got, each.want)
		}
	}
}
