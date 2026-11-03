package plan

import (
	"errors"
	"io/fs"
	"os"
)

// Forget removes every plan the name reads: a seat renamed into a free name starts without the
// plan a gone seat left there.
func Forget(current string) error {
	for _, each := range Names(current) {
		if err := os.Remove(seatFile("plan", each, "md")); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
	}
	return nil
}
