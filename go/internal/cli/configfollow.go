package cli

import (
	"reflect"
	"time"

	"agentkit/internal/matrix"
	"agentkit/internal/seat"
	"agentkit/internal/terminal"
)

// followEvery is how often an open seat's `c` reads its record while no key comes (menu.STIR).
const followEvery = time.Second

// readConfigKey is the next key on `c`, a seat's record read again every followEvery meanwhile, on
// the goroutine that draws so a read cannot land over a save (menu.config_matrix).  A record that
// reads differently becomes the selection and says `wake`, to be drawn; one that reads the same
// draws nothing, so a screen left alone writes nothing, and one that will not read keeps the last.
func readConfigKey(session string, c *matrix.Configuration, keyboard *terminal.Keyboard) terminal.Key {
	if session == "" {
		return keyboard.ReadKey()
	}
	follow := time.AfterFunc(followEvery, keyboard.Wake)
	defer follow.Stop()
	for {
		key := keyboard.ReadKey()
		if key.Name != "wake" {
			return key
		}
		if read, err := seat.ConfigSelection(session); err == nil && read != nil && !reflect.DeepEqual(read, c.Selected) {
			c.Selected = read
			return key
		}
		follow.Reset(followEvery)
	}
}
