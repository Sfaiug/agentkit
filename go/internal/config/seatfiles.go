package config

import (
	"path/filepath"
	"strings"
)

// seatFiles are the files a seat owns under state/ as `<kind>-<seat>.<ext>`, each kind's extension:
// Python's config.SEAT_FILES, where each says what it holds and its test holds this copy to.  A
// rename moves them, and a stop and the daily collector find them by this table.
var seatFiles = map[string]string{"log": "txt", "session": "json", "notify": "json", "card": "json", "seat": "json",
	"hook": "json", "plan": "md", "stop": "json", "live": "txt", "title": "json", "input": "jsonl", "rulebook": "md",
	"verify": "lock", "unverified": "txt", "verified": "txt", "checked": "txt", "pictures": "jsonl", "rules": "md",
	"change": "md", "held": "md", "launch": "sh", "refused": "txt", "handover": "md", "tell": "json"}

// SeatFileNames is the name of the seat's file of each kind, by kind.
func SeatFileNames(seat string) map[string]string {
	names := map[string]string{}
	for kind, ext := range seatFiles {
		names[kind] = kind + "-" + seat + "." + ext
	}
	return names
}

// SeatFileOwner is the seat a state file is one of by its name, as Python's
// config.seat_file_owner reads it: `<kind>-<seat>.<anything>` of a kind in the table, its locks
// and temporaries among them.
func SeatFileOwner(file string) (string, bool) {
	at := strings.LastIndexByte(file, '.')
	if at < 0 || at == len(file)-1 {
		return "", false
	}
	kind, seat, _ := strings.Cut(file[:at], "-")
	_, known := seatFiles[kind]
	return seat, seat != "" && known
}

// SeatRecords is the paths of one kind's `<kind>-<seat>.json` files in name order, as Python's
// config.seat_files lists a kind it keeps as JSON.
func SeatRecords(kind string) []string {
	return Glob(filepath.Join(Home(), "state"), kind+"-*.json")
}
