package plan

import (
	"time"
	"unicode/utf8"
)

// fromISO is the moment text names as Python's datetime.fromisoformat reads it, in CPython's
// C reader: extended and basic forms, ISO week dates among them, any one character between
// date and time, and a time with no offset in UTC; false where Python raises ValueError.
func fromISO(text string) (time.Time, bool) {
	if len(text) < 7 {
		return time.Time{}, false
	}
	split := dateEnd(text)
	if split < 0 {
		return time.Time{}, false
	}
	year, month, day, ok := isoDate(text, split)
	var clock [4]int
	var offset time.Duration
	if ok && len(text) > split {
		_, width := utf8.DecodeRuneInString(text[split:])
		clock, offset, ok = isoTime(text, split+width)
	}
	date := time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
	if !ok || year < 1 || year > 9999 || month < 1 || month > 12 || date.Day() != day ||
		clock[0] > 23 || clock[1] > 59 || clock[2] > 59 || offset <= -24*time.Hour || offset >= 24*time.Hour {
		return time.Time{}, false
	}
	return date.Add(time.Duration(clock[0])*time.Hour + time.Duration(clock[1])*time.Minute +
		time.Duration(clock[2])*time.Second + time.Duration(clock[3])*time.Microsecond - offset), true
}

// at is text's byte i, or 0 past its end: C reads on to the string's NUL.
func at(text string, i int) byte {
	if i < len(text) {
		return text[i]
	}
	return 0
}

func digit(c byte) bool { return '0' <= c && c <= '9' }

// digits is the number the n ASCII digits at i make, and where they end.
func digits(text string, i, n int) (value, end int, ok bool) {
	for ; n > 0; i, n = i+1, n-1 {
		if !digit(at(text, i)) {
			return 0, i, false
		}
		value = value*10 + int(text[i]-'0')
	}
	return value, i, true
}

// dateEnd is where the date ends, as Python's _find_isoformat_datetime_separator finds it,
// -1 for none: `2026-11-06` 10, `20261106` 8, `2026-W45` 8, `2026W45` 7, `2026-W45-5` 10,
// `2026W455` 8.
func dateEnd(text string) int {
	n := len(text)
	switch {
	case n == 7:
		return 7
	case text[4] == '-' && text[5] != 'W':
		return 10
	case text[4] == '-' && n > 8 && text[8] == '-':
		if n == 9 {
			return -1
		}
		if n > 10 && digit(text[10]) {
			return 8 // `2026-W45-12:00`: Python takes the time's dash for the separator
		}
		return 10
	case text[4] == '-':
		return 8
	case text[4] != 'W':
		return 8
	}
	idx := 7
	for idx < n && digit(text[idx]) {
		idx++
	}
	if idx < 9 {
		return idx
	}
	return 7 + idx%2
}

// isoDate is the date text holds before end, as Python's parse_isoformat_date reads it, a week
// date as the day it names.
func isoDate(text string, end int) (year, month, day int, ok bool) {
	year, p, ok := digits(text, 0, 4)
	if !ok {
		return 0, 0, 0, false
	}
	dashed := at(text, p) == '-'
	if dashed {
		p++
	}
	if at(text, p) != 'W' {
		if month, p, ok = digits(text, p, 2); ok && dashed {
			ok, p = at(text, p) == '-', p+1
		}
		if ok {
			day, _, ok = digits(text, p, 2)
		}
		return year, month, day, ok
	}
	week, p, ok := digits(text, p+1, 2)
	weekday := 1
	if ok && p < end {
		if dashed {
			ok, p = at(text, p) == '-', p+1
		}
		if ok {
			weekday, _, ok = digits(text, p, 1)
		}
	}
	jan1 := time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC)
	long := jan1.Weekday() == time.Thursday || jan1.Weekday() == time.Wednesday && jan1.AddDate(1, 0, -1).YearDay() == 366
	if !ok || year < 1 || year > 9999 || week < 1 || week > 53 || week == 53 && !long || weekday < 1 || weekday > 7 {
		return 0, 0, 0, false
	}
	// week 1 is the one holding 4 January, and starts on a Monday
	jan4 := jan1.AddDate(0, 0, 3)
	date := jan4.AddDate(0, 0, (week-1)*7+weekday-1-(int(jan4.Weekday())+6)%7)
	return date.Year(), int(date.Month()), date.Day(), true
}

// isoTime is the clock (hours, minutes, seconds, microseconds) text holds from p to its end and
// its offset east of UTC, as Python's parse_isoformat_time reads them.
func isoTime(text string, p int) (clock [4]int, offset time.Duration, ok bool) {
	end, zone := len(text), p
	for c := at(text, zone); c != 'Z' && c != '+' && c != '-'; c = at(text, zone) {
		if zone++; zone >= end {
			break
		}
	}
	clock, more := hhmmssff(text, p, zone)
	switch {
	case more < 0:
		return clock, 0, false
	case zone == end:
		return clock, 0, more == 0
	case text[zone] == 'Z':
		return clock, 0, at(text, zone+1) == 0
	}
	east, more := hhmmssff(text, zone+1, end)
	seconds := time.Duration(east[0]*3600+east[1]*60+east[2]) * time.Second
	if seconds != 0 { // Python's UTC drops the microseconds of an offset of no whole second
		offset = seconds + time.Duration(east[3])*time.Microsecond
	}
	if text[zone] == '-' {
		offset = -offset
	}
	return clock, offset, more == 0
}

// hhmmssff is the clock text holds from p, its end at end, as Python's parse_hh_mm_ss_ff reads
// it: HH[:?MM[:?SS[{.,}ffffff]]], digits past six dropped.  More is -1 for none, 1 where text
// goes on past it, and 0 where it ends there.
func hhmmssff(text string, p, end int) (clock [4]int, more int) {
	colons := true
	for i := 0; i < 3; i++ {
		var ok bool
		if clock[i], p, ok = digits(text, p, 2); !ok {
			return clock, -1
		}
		c := at(text, p)
		p++
		if i == 0 {
			colons = c == ':'
		}
		if p >= end {
			return clock, min(int(c), 1)
		}
		if colons && c == ':' {
			continue
		}
		if c == '.' || c == ',' {
			break
		}
		if colons {
			return clock, -1
		}
		p--
	}
	n := min(end-p, 6)
	fraction, p, ok := digits(text, p, n)
	if !ok {
		return clock, -1
	}
	for ; n < 6; n++ {
		fraction *= 10
	}
	for digit(at(text, p)) {
		p++
	}
	clock[3] = fraction
	return clock, min(int(at(text, p)), 1)
}
