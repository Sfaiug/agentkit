package plan

import (
	"testing"
	"time"
)

// Each moment as Python 3.13's datetime.fromisoformat reads it, in UTC; "" where it refuses.
func TestFromISOReadsWhatPythonReads(t *testing.T) {
	for text, want := range map[string]string{
		"2026-11-03T12:00:00.123456+05:30": "2026-11-03T06:30:00.123456Z",
		"20261103T120000,5-0130":           "2026-11-03T13:30:00.5Z",
		"2026-W45-3T12:30":                 "2026-11-04T12:30:00Z",
		"2026W453":                         "2026-11-04T00:00:00Z",
		"2026-W45":                         "2026-11-02T00:00:00Z",
		"2026W45T12":                       "2026-11-02T12:00:00Z",
		"2020-W53-7":                       "2021-01-03T00:00:00Z",
		"2026-11-03 12":                    "2026-11-03T12:00:00Z",
		"2026-11-03é12:00":                 "2026-11-03T12:00:00Z",
		"2026-11-03T12:00:00.1234567":      "2026-11-03T12:00:00.123456Z",
		"2026-11-03T12:00+05:30:15.25":     "2026-11-03T06:29:44.75Z",
		"2026-W00":                         "",
		"2021-W53":                         "",
		"2026-11-03T24:00":                 "",
		"2026-11-03T12:00+24:00":           "",
		"2026-02-29":                       "",
		"2026-11-03T":                      "",
		"not a date":                       "",
	} {
		at, ok := fromISO(text)
		if got := at.UTC().Format(time.RFC3339Nano); !ok && want != "" || ok && got != want {
			t.Errorf("%q: read %s %v, Python reads %q", text, got, ok, want)
		}
	}
}
