package terminal

import (
	"strings"
	"testing"
)

func TestAFrameUpCrossesWithWhatItWasDrawnForAndIsWrittenOnlyThere(t *testing.T) {
	var before, after strings.Builder
	old, screen := NewPainter(&before), Screen{width: 6, height: 4, background: "rgb:0000/0000/0000"}
	if old.Up() != nil {
		t.Fatal("nothing drawn yet handed on a frame")
	}
	old.Write([]string{"acme", "123456"}, screen)
	if got := string(old.Up()); got != "6 4 rgb:0000/0000/0000\nacme\n123456" {
		t.Fatalf("handed on %q", got)
	}
	for _, other := range []Screen{{width: 5, height: 4, background: screen.background},
		{width: 6, height: 4, background: "rgb:ffff/ffff/ffff"}, {width: 6, height: 4}} {
		NewPainter(&after).Restore(old.Up(), other)
	}
	NewPainter(&after).Restore(nil, screen)
	NewPainter(&after).Restore([]byte("6 4\nacme\n123456"), Screen{width: 6, height: 4}) // the release before this
	if after.Len() != 0 {
		t.Fatalf("wrote %q on another terminal or with nothing handed", after.String())
	}
	NewPainter(&after).Restore(old.Up(), screen)
	if want := "\x1b[1;1Hacme\x1b[K\x1b[2;1H123456\x1b[?2026l"; after.String() != want {
		t.Fatalf("wrote %q, want %q", after.String(), want)
	}
	if old.Forget(); old.Up() != nil {
		t.Fatal("a frame the terminal may no longer hold was handed on")
	}
}
