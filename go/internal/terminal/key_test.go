package terminal

import (
	"strings"
	"testing"
	"time"
)

// typed is a keyboard that sent these bytes at once, and nothing after.
func typed(sent string) (byte, nextByte) {
	rest := []byte(sent[1:])
	return sent[0], func(time.Duration) (byte, bool) {
		if len(rest) == 0 {
			return 0, false
		}
		first := rest[0]
		rest = rest[1:]
		return first, true
	}
}

func TestEachKeyIsAsFewBytesAsMakeIt(t *testing.T) {
	for sent, want := range map[string]Key{
		"\x1b": {Name: "esc"}, "\x1b[A": {Name: "up"}, "\x1bOD": {Name: "left"}, "\r": {Name: "enter"},
		"\x1b[<35;10;4M": {Name: "pointer", Mouse: Mouse{Button: 35, Column: 10, Row: 4}}, "q": {Name: "char", Char: "q"}, "é": {Name: "char", Char: "é"},
		"\x04": {Name: "eof"}, "\x1b[5~": {Name: "other"},
	} {
		first, next := typed(sent)
		if got, kept, ok := spell(first, next); !ok || got != want || kept != nil {
			t.Errorf("%q: %v %q %v", sent, got, kept, ok)
		}
	}
	// a key typed right after a lone Esc is the next key's
	if first, next := typed("\x1bn"); true {
		if got, kept, _ := spell(first, next); got.Name != "esc" || string(kept) != "n" {
			t.Errorf("esc then n: %v %q", got, kept)
		}
	}
}

func TestATerminalsLateAnswerIsNoKey(t *testing.T) {
	for _, sent := range []string{"\x1b]11;rgb:ffff/ffff/ffff\x1b\\", "\x1b]11;rgb:0000/0000/0000\x07", "\x1b[?1;2c"} {
		first, next := typed(sent)
		if _, _, ok := spell(first, next); ok {
			t.Errorf("%q read as a key", sent)
		}
	}
}

// An answer naming no colour is told from a dark one: it keeps nothing (keep).
func TestABackgroundIsLightOnceItsLumaIsPastHalfWay(t *testing.T) {
	for answer, want := range map[string][2]any{"rgb:8080/8080/8080": {"808080", true}, "rgb:7f7f/7f7f/7f7f": {"7f7f7f", false},
		"rgb:ff/ff/ff": {"ffffff", true}, "rgba:0000/0000/0000/ffff": {"000000", false}, "": {"", false}, "black": {"", false}} {
		if rgb, light := background(answer); [2]any{rgb, light} != want {
			t.Errorf("%q: %v %v", answer, rgb, light)
		}
	}
}

func TestAScreenLeftAloneWritesNothing(t *testing.T) {
	var out writes
	painter, screen := NewPainter(&out), Screen{width: 4, height: 5}
	painter.Write([]string{"ab", "abcd"}, screen)
	if want := "\x1b[?2026h\x1b[1;1Hab\x1b[K\x1b[2;1Habcd\x1b[3;1H\x1b[J\x1b[?2026l"; len(out) != 1 || out[0] != want {
		t.Fatalf("%q", out)
	}
	painter.Write([]string{"ab", "abcd"}, screen)
	if len(out) != 1 {
		t.Fatalf("written again: %q", out)
	}
	painter.Forget()
	painter.Write([]string{"ab", "abcd"}, screen)
	painter.Write([]string{"ab", "abcd"}, Screen{width: 5, height: 5})
	if len(out) != 3 {
		t.Fatalf("a forgotten or resized frame is written whole: %q", out)
	}
}

func TestScreenPaintAndFadeKeepTerminalBackground(t *testing.T) {
	for _, s := range []Screen{{depth: 24}, {depth: 256, ground: "5f5f87"}, {depth: 256}} {
		if got := s.paint("x"); !strings.HasPrefix(got, "\x1b[49;38;") {
			t.Errorf("%+v painted %q", s, got)
		}
	}
	// On a saturated light background dim and info stay distinct.
	light := Screen{depth: 24, theme: white, ground: "18c05c"}
	if light.colour("dim") == light.colour("info") {
		t.Fatalf("dim and info collided on #18c05c: %s", light.colour("dim"))
	}
	// A channel value of 39 or 0 inside SGR 48 is never read as a foreground reset during a fade.
	fadeScreen := Screen{depth: 24, theme: white, ground: "c5dc27"}
	got := fadeScreen.Fade("\x1b[38;2;89;103;36;48;2;171;195;39midle\x1b[0m", 0.01)
	want := strings.ReplaceAll(fadeScreen.Fade("\x1b[38;2;89;103;36;48;2;171;195;40midle\x1b[0m", 0.01), ";40m", ";39m")
	if got != want {
		t.Fatalf("fade misread SGR 48 channel 39:\n got: %q\nwant: %q", got, want)
	}
}

type writes []string

func (w *writes) Write(data []byte) (int, error) {
	*w = append(*w, string(data))
	return len(data), nil
}
