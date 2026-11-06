package cli

import (
	"reflect"
	"time"

	"agentkit/internal/matrix"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// followEvery is how often an open seat's `c` reads its record (menu.STIR).
const followEvery = time.Second

// followSeat reads `c`'s keys, a seat's record read again once followEvery has passed since it
// last was, however many keys or pointer moves come meanwhile, and on the goroutine that draws so
// a read cannot land over a save (menu.config_matrix).  A record that reads differently becomes
// the selection and says `wake`, to be drawn; one that reads the same draws nothing, so a screen
// left alone writes nothing, and one that will not read keeps the last that did.
func followSeat(session string, keyboard *terminal.Keyboard) func(*matrix.Configuration) terminal.Key {
	due := time.Now().Add(followEvery) // the record was read as `c` opened
	return func(c *matrix.Configuration) terminal.Key {
		if session == "" {
			return keyboard.ReadKey()
		}
		for {
			if !time.Now().Before(due) {
				due = time.Now().Add(followEvery)
				if read, err := seat.ConfigSelection(session); err == nil && read != nil && !reflect.DeepEqual(read, c.Selected) {
					c.Selected = read
					return terminal.Key{Name: "wake"}
				}
			}
			follow := time.AfterFunc(time.Until(due), keyboard.Wake)
			key := keyboard.ReadKey()
			follow.Stop()
			if key.Name != "wake" {
				return key
			}
		}
	}
}
