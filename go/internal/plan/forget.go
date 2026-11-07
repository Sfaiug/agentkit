package plan

import (
	"errors"
	"io/fs"
	"os"
)

// Forget removes every plan the name reads, and the pictures kept beside it for its done check
// (`ak orch look`): a seat renamed into a free name starts without the plan and pictures a gone
// seat left there.
func Forget(current string) error {
	for _, each := range Names(current) {
		for _, path := range []string{seatFile("plan", each, "md"), seatFile("pictures", each, "jsonl")} {
			if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
				return err
			}
		}
	}
	return nil
}
