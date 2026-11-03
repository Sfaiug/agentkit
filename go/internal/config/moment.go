package config

import (
	"fmt"
	"strconv"
	"time"
)

// moment is a TOML date, date-time or time as Python's isoformat() writes what tomllib read of
// it: its kind and its offset, which a time.Time would not keep, are what a save writes back.
type moment string

// dated is a date and time match as a moment; false where Python's date holds no such day.
func dated(match []string) (moment, bool) {
	year, _ := strconv.Atoi(match[1])
	month, _ := strconv.Atoi(match[2])
	day, _ := strconv.Atoi(match[3])
	text := fmt.Sprintf("%04d-%02d-%02d", year, month, day)
	if match[4] != "" {
		text += "T" + onClock(match[4:8])
	}
	switch {
	case match[8] != "":
		text += "+00:00"
	case match[9] != "":
		sign := match[9]
		if match[10] == "00" && match[11] == "00" {
			sign = "+" // a zero offset is UTC's whichever its sign
		}
		text += sign + match[10] + ":" + match[11]
	}
	return moment(text), year >= 1 && time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC).Day() == day
}

// onClock is a clock's hour, minute and second, and its fraction to the microsecond where that is
// not zero, as Python's time.isoformat() writes them.
func onClock(parts []string) string {
	text := parts[0] + ":" + parts[1] + ":" + parts[2]
	if micros, _ := strconv.Atoi((parts[3] + "000000")[:6]); micros != 0 {
		text += fmt.Sprintf(".%06d", micros)
	}
	return text
}
