package plan

import (
	"context"
	"os"
	"strconv"
	"strings"

	"agentkit/internal/notify"
)

// unverified is how many deliveries are owed a verification of the seat's plan begun after them,
// Python's `unverified-<seat>.txt` (`plan._owed`), read under the seat's lock.  A count, not a
// mark: a verification that checked every line takes off only those it read as it began, so one
// counted while it checked stays owed.
func unverified(current string) int {
	data, err := os.ReadFile(seatFile("unverified", current, "txt"))
	count, unread := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || unread != nil {
		return 0
	}
	return count
}

// owe counts more deliveries owed, or fewer for a verification that checked them, under the
// seat's lock; the file goes with the last.  Written whole, so a process killed meanwhile never
// leaves a count nothing reads.
func owe(current string, more int) error {
	path, left := seatFile("unverified", current, "txt"), unverified(current)+more
	if left <= 0 {
		if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
			return err
		}
		return nil
	}
	fresh := path + ".new"
	if err := os.WriteFile(fresh, []byte(strconv.Itoa(left)+"\n"), 0o600); err != nil {
		return err
	}
	return os.Rename(fresh, path)
}

// settle verifies every open line again while a delivery is owed a verification begun after it,
// unless another process verifies: that one settles once it lets go.  Every process asks once it
// lets go of the lock, and a delivery once it counted itself owed, so none is left owed with
// nobody verifying.  A verification that errs or could not check a line leaves the count to the
// next delivery or `ak plan`: trying again at once would only repeat what failed.  Each
// verification sees ready as verify gives it.
func settle(ctx context.Context, name string, ready func(current string, lines []string) error) error {
	for {
		due := false
		if err := notify.Held(ctx, name, func(current string) error {
			due = unverified(current) > 0
			return nil
		}); err != nil || !due {
			return err
		}
		whole := false
		if err := verifying(ctx, name, false, func() (err error) {
			whole, err = verify(ctx, name, "", ready)
			return err
		}); err != nil || !whole {
			return err
		}
	}
}
