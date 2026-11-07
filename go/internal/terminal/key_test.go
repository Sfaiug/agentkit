package terminal

import (
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

func TestABackgroundIsLightOnceItsLumaIsPastHalfWay(t *testing.T) {
	for answer, light := range map[string]bool{"rgb:8080/8080/8080": true, "rgb:7f7f/7f7f/7f7f": false, "rgb:ff/ff/ff": true,
		"rgba:0000/0000/0000/ffff": false, "": false} {
		if isLight(answer) != light {
			t.Errorf("%q", answer)
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

type writes []string

func (w *writes) Write(data []byte) (int, error) {
	*w = append(*w, string(data))
	return len(data), nil
}
