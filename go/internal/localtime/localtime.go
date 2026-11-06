// Package localtime makes Go's local time the C library's, which Python's time and datetime read.
package localtime

import (
	"encoding/binary"
	"os"
	"regexp"
	"slices"
	"strings"
	"time"
)

// undated is a POSIX rule naming summer time but not its dates, such as `AKT5AKDT`.  The C library
// takes them from the host: glibc shifts zoneinfo's posixrules by its own arithmetic, which keeps an
// offset an earlier rule left, and other C libraries date it otherwise.
var undated = regexp.MustCompile(`^(<[^>]*>|[A-Za-z]+)[+-]?[0-9]+(:[0-9]+){0,2}(<[^>]*>|[A-Za-z]+)([+-]?[0-9]+(:[0-9]+){0,2})?,?$`)

// Read is called once, as the program starts, and is whether Go's local time is now the C
// library's: where Go found no zone file for TZ and fell back to UTC, it reads TZ as the C library
// then does, as a POSIX rule such as `AKT-5`, but for an undated one, whose local time is Python's
// to read.
func Read() bool {
	if time.Local.String() != "UTC" {
		return true
	}
	rule := strings.TrimPrefix(os.Getenv("TZ"), ":")
	if undated.MatchString(rule) {
		return false
	}
	if local, err := time.LoadLocationFromTZData(rule, zone(rule)); err == nil {
		time.Local = local
	}
	return true
}

// zone is a zone file of one zone, UTC, and no transition, whose footer is rule: Go's reader reads
// a footer in the C library's grammar, summer time included, and a rule neither reads leaves UTC.
func zone(rule string) []byte {
	// the version 1 header and block; version 2 repeats them with wider times, of which none
	block := []byte("TZif2" + strings.Repeat("\x00", 15))
	for _, count := range []uint32{0, 0, 0, 0, 1, 4} { // indicators, leaps, transitions, zones, bytes of names
		block = binary.BigEndian.AppendUint32(block, count)
	}
	block = append(block, "\x00\x00\x00\x00\x00\x00UTC\x00"...) // offset 0, standard time, named UTC
	return slices.Concat(block, block, []byte("\n"+rule+"\n"))
}
