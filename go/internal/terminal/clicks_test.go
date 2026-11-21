package terminal

import "testing"

// A left release whose press began before this screen, or another button's press or release, is
// "other" (no click and no pointer highlight); a left press followed by a release is a click,
// even with a drag between them, and moves and wheel reports pass through.
func TestClicksKey(t *testing.T) {
	var clicks Clicks
	left := func(released bool) Key {
		return Key{Name: "pointer", Mouse: Mouse{Column: 4, Row: 6, Released: released}}
	}
	if key, clicked := clicks.Key(left(true)); key.Name != "other" || clicked {
		t.Fatalf("stray release = (%+v, %v), want (other, false)", key, clicked)
	}
	for _, released := range []bool{false, true} {
		right := Key{Name: "pointer", Mouse: Mouse{Column: 4, Row: 6, Button: 2, Released: released}}
		if key, clicked := clicks.Key(right); key.Name != "other" || clicked {
			t.Fatalf("right button released=%v = (%+v, %v), want (other, false)", released, key, clicked)
		}
	}
	if key, clicked := clicks.Key(left(false)); key != (Key{}) || clicked {
		t.Fatalf("left press = (%+v, %v), want (zero, false)", key, clicked)
	}
	drag := Key{Name: "pointer", Mouse: Mouse{Column: 5, Row: 6, Button: 32}}
	if key, clicked := clicks.Key(drag); key != drag || clicked {
		t.Fatalf("drag = (%+v, %v), want (%+v, false)", key, clicked, drag)
	}
	if key, clicked := clicks.Key(left(true)); key != left(true) || !clicked {
		t.Fatalf("left release after press = (%+v, %v), want (%+v, true)", key, clicked, left(true))
	}
	if key, clicked := clicks.Key(left(true)); key.Name != "other" || clicked {
		t.Fatalf("second release = (%+v, %v), want (other, false)", key, clicked)
	}
	wheel := Key{Name: "pointer", Mouse: Mouse{Column: 4, Row: 6, Button: 64, Notches: -1}}
	if key, clicked := clicks.Key(wheel); key != wheel || clicked {
		t.Fatalf("wheel = (%+v, %v), want (%+v, false)", key, clicked, wheel)
	}
}
