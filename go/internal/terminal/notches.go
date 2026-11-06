//go:build linux || darwin

package terminal

// notches is a key off the wheel and every wheel report already sent after it, read whole: one key
// as far as all of them go, false where they cancel out, and the key read past them kept for the
// next read.  A trackpad swipe sends a report a row of travel, faster than a screen draws; a draw
// each went on for seconds after the finger stopped (3 Nov 2026).
func (k *Keyboard) notches(key Key) (Key, bool) {
	for each := key; ; {
		key.Mouse.Notches += travel(each)
		first, sent := k.next(0)
		if !sent {
			break
		}
		var kept []byte
		var ok bool
		each, kept, ok = spell(first, k.next)
		k.keyed = append(kept, k.keyed...)
		if ok && !wheel(each) {
			k.Unread(each)
			break
		}
	}
	return key, key.Mouse.Notches != 0
}

// wheel is whether a key is a report of the wheel.
func wheel(key Key) bool { return key.Name == "pointer" && key.Mouse.Button&64 != 0 }

// travel is the rows one report of the wheel moves, down above 0: none sideways, or off the wheel.
func travel(key Key) int {
	switch {
	case !wheel(key) || key.Mouse.Button&3 > 1:
		return 0
	case key.Mouse.Button&1 != 0:
		return 1
	}
	return -1
}
