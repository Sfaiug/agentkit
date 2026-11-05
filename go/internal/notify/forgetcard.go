package notify

import (
	"context"
	"errors"
	"io/fs"
	"os"
)

// ForgetCard is Python's notify.forget_card: the card of a seat that is gone off the host, under
// the seat's typing lock, which stays for whoever holds or waits on it; a question's episode
// retired first where Discord has not taken its card yet, and what went out left as it went.
// A card that is a link is not the seat's, and one under an old name leading to a renamed seat
// is not this one's.
func ForgetCard(name string, log func(string)) error {
	path := seatFile("card", name, "json")
	if info, err := os.Lstat(path); err != nil || !info.Mode().IsRegular() {
		return nil
	}
	closed := false
	err := Held(context.Background(), name, func(current string) error {
		if current != name {
			return nil
		}
		card, err := readObject(path)
		if err != nil && !errors.Is(err, errNotObject) {
			return err
		}
		if card != nil && card.Str("word") == "needs you" {
			if err := retire(card); err != nil {
				return err
			}
		}
		if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		closed = true
		return nil
	})
	if closed {
		log("closed the card of " + name + ": no seat holds it any more")
	}
	return err
}
