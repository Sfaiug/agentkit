// Package localtime makes Go's local time the C library's, which Python's time and datetime read.
package localtime

import (
	"encoding/binary"
	"os"
	"slices"
	"strings"
	"time"
)

// Read is called once, as the program starts: where Go found no zone file for TZ and fell back to
// UTC, it reads TZ as the C library then does, as a POSIX rule such as `AKT-5`.
func Read() {
	if time.Local.String() == "UTC" {
		rule := strings.TrimPrefix(os.Getenv("TZ"), ":")
		if local, err := time.LoadLocationFromTZData(rule, zone(rule)); err == nil {
			time.Local = local
		}
	}
}

// posix is a zone file whose footer is rule and no more: Go's reader reads a footer in the C
// library's grammar, summer time included, and a rule neither reads leaves UTC.
func posix(rule string) []byte {
	return tzif(nil, nil, [2]int32{}, [2]string{"UTC", "UTC"}, rule)
}

// tzif is a zone file of version 2 changing at each of at to standard time (0) or summer time (1),
// as to says, each of the offset east and name its index gives, and footer after the last change.
// Go reads only its 64-bit data, so the 32-bit data before them are empty.
func tzif(at []int64, to []byte, offsets [2]int32, names [2]string, footer string) []byte {
	head := []byte("TZif2" + strings.Repeat("\x00", 15))
	empty := slices.Concat(head, make([]byte, 24))
	chars := names[0] + "\x00" + names[1] + "\x00"
	data := head
	for _, count := range []int{0, 0, 0, len(at), 2, len(chars)} { // indicators, leaps, changes, types, bytes of names
		data = binary.BigEndian.AppendUint32(data, uint32(count))
	}
	for _, when := range at {
		data = binary.BigEndian.AppendUint64(data, uint64(when))
	}
	data = append(data, to...)
	for i, offset := range offsets {
		data = append(binary.BigEndian.AppendUint32(data, uint32(offset)), byte(i), byte(i*(len(names[0])+1)))
	}
	return slices.Concat(empty, data, []byte(chars+"\n"+footer+"\n"))
}
