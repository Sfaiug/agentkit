package terminal

import "time"

// A Key is what the keyboard sent, or what else ended a wait for it: `char` carries its Char; `esc`,
// `enter`, `up`, `down`, `left`, `right`, `tab`, `space` and `backspace` are themselves; `pointer`
// is a report of the mouse, `other` a sequence no screen asks about and `eof` a keyboard that is
// gone.  `again` asks for the whole frame anew (a resize, a return from a stop) and `wake` says
// Keyboard.Wake was called.
type Key struct{ Name, Char string }

// A nextByte is the next byte the keyboard sent within wait, false where none came or it is gone.
type nextByte func(wait time.Duration) (byte, bool)

// spell makes one key of as few bytes as it takes after first, so what comes after stays for whoever
// reads next; ok is false for a terminal's answer, which is no key, and kept is a byte read past the
// key.  An Esc alone is told from a sequence's start by what was sent with it: a terminal writes a
// sequence whole, so a lone Esc needs no wait.
func spell(first byte, next nextByte) (key Key, kept []byte, ok bool) {
	switch {
	case first == 0x1b:
		return sequence(next)
	case first == '\r' || first == '\n':
		return Key{Name: "enter"}, nil, true
	case first == '\t':
		return Key{Name: "tab"}, nil, true
	case first == ' ':
		return Key{Name: "space"}, nil, true
	case first == 0x7f || first == 0x08:
		return Key{Name: "backspace"}, nil, true
	case first == 0x04:
		return Key{Name: "eof"}, nil, true
	case first < 0x20:
		return Key{Name: "other"}, nil, true
	}
	raw, size := []byte{first}, 1
	switch {
	case first >= 0xf0:
		size = 4
	case first >= 0xe0:
		size = 3
	case first >= 0xc0:
		size = 2
	}
	for len(raw) < size {
		more, got := next(50 * time.Millisecond)
		if !got {
			break
		}
		raw = append(raw, more)
	}
	return Key{Name: "char", Char: string(raw)}, nil, true
}

// sequence is what an Esc starts: Esc itself, with the byte typed right after it kept for the next
// key, an arrow, a report of the mouse, `other`, or a terminal's answer come too late for Sense.
func sequence(next nextByte) (Key, []byte, bool) {
	kind, sent := next(0)
	if !sent {
		return Key{Name: "esc"}, nil, true
	}
	if kind == ']' { // read to its end, BEL or ST, so none of it is a key
		var last byte
		for {
			each, got := next(50 * time.Millisecond)
			if !got || each == 0x07 || last == 0x1b && each == '\\' {
				return Key{}, nil, false
			}
			last = each
		}
	}
	if kind != '[' && kind != 'O' {
		return Key{Name: "esc"}, []byte{kind}, true
	}
	var body []byte
	for {
		each, got := next(50 * time.Millisecond)
		if !got {
			return Key{Name: "other"}, nil, true
		}
		body = append(body, each)
		if kind == 'O' || 0x40 <= each && each <= 0x7e {
			break
		}
	}
	final := body[len(body)-1]
	switch {
	case body[0] == '?' && final == 'c':
		return Key{}, nil, false // its attributes (DA1), come after Sense stopped waiting
	case body[0] == '<' && (final == 'M' || final == 'm'):
		return Key{Name: "pointer"}, nil, true
	case kind == 'O' && final == 'M':
		return Key{Name: "enter"}, nil, true // the keypad's own Enter
	}
	name, known := map[byte]string{'A': "up", 'B': "down", 'C': "right", 'D': "left"}[final]
	if !known {
		name = "other"
	}
	return Key{Name: name}, nil, true
}
