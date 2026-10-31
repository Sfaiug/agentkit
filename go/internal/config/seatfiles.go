package config

import (
	"slices"
	"strings"
)

// seatKinds are the kinds of file a seat owns under state/ as `<kind>-<seat>.<ext>`: the keys of
// Python's config.SEAT_FILES, where each says what it holds and its test holds this copy to.  A
// rename moves them, and a stop and the daily collector find them by this table.
var seatKinds = []string{"log", "session", "notify", "card", "seat", "hook", "plan", "stop", "live", "title",
	"input", "rulebook", "verify", "verified", "rules", "change", "held", "launch", "refused", "handover", "tell"}

// SeatFileOwner is the seat a state file is one of by its name, as Python's
// config.seat_file_owner reads it: `<kind>-<seat>.<anything>` of a kind in the table, its locks
// and temporaries among them.
func SeatFileOwner(file string) (string, bool) {
	at := strings.LastIndexByte(file, '.')
	if at < 0 || at == len(file)-1 {
		return "", false
	}
	kind, seat, _ := strings.Cut(file[:at], "-")
	return seat, seat != "" && slices.Contains(seatKinds, kind)
}
