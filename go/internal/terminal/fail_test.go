package terminal

import "testing"

// A failed run's bar on `Limits` is drawn in FAIL's role as Python's STATE_STYLES and ROLES hold it:
// the strings Python's share_line writes in the black theme and the white and in eight colours.
func TestAFailedBarIsDrawnInFailsColour(t *testing.T) {
	for _, each := range []struct {
		screen Screen
		want   string
	}{
		{Screen{depth: 24}, "\x1b[38;2;254;117;111m━\x1b[0m\x1b[38;2;254;117;111m━\x1b[0m"},
		{Screen{depth: 24, theme: white}, "\x1b[38;2;197;42;47m━\x1b[0m\x1b[38;2;197;42;47m━\x1b[0m"},
		{Screen{depth: 8}, "\x1b[31m━━\x1b[0m"},
	} {
		if got := each.screen.ShareLine(1, 2, "FAIL"); got != each.want {
			t.Errorf("%+v: %q, want %q", each.screen, got, each.want)
		}
	}
}
