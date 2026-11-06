package terminal

import (
	"strconv"
	"strings"
)

// Mouse is an SGR report: one-based terminal coordinates, its button and whether it was released.
// Notches, on the wheel, is its travel, a row a notch and down above 0: of its report and every one
// sent with it (Keyboard.ReadKey), never none.
type Mouse struct {
	Column, Row, Button, Notches int
	Released                     bool
}

func mouseKey(body string) Key {
	parts := strings.Split(body[1:len(body)-1], ";")
	if len(parts) != 3 {
		return Key{Name: "other"}
	}
	var values [3]int
	for i, part := range parts {
		n, err := strconv.Atoi(part)
		if err != nil || n < 0 || i > 0 && n == 0 {
			return Key{Name: "other"}
		}
		values[i] = n
	}
	return Key{Name: "pointer", Mouse: Mouse{Button: values[0], Column: values[1], Row: values[2], Released: strings.HasSuffix(body, "m")}}
}
