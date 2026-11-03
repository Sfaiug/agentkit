package config

import "testing"

// A date, a date-time and a time are written back as Python's isoformat() writes what tomllib
// read: each kind kept, a fraction to the microsecond, a zero offset UTC's.
func TestMomentsAreWrittenAsPythonWritesThem(t *testing.T) {
	own := "d = 1979-05-27\nlt = 07:32:00.5\nldt = 1979-05-27t07:32:00\nodt = 1979-05-27 07:32:00Z\n" +
		"neg = 1979-05-27T07:32:00-00:00\noff = 1979-05-27T07:32:00.9999999-07:30\n"
	want := "d = 1979-05-27\nlt = 07:32:00.500000\nldt = 1979-05-27T07:32:00\nodt = 1979-05-27T07:32:00+00:00\n" +
		"neg = 1979-05-27T07:32:00+00:00\noff = 1979-05-27T07:32:00.999999-07:30\n"
	if got, _, err := Carry("", own); got != want || err != nil {
		t.Fatalf("Carry = %q %v, want %q", got, err, want)
	}
}
