package host

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPressureIsTheLargerShareOfTheLastMinute(t *testing.T) {
	path := filepath.Join(t.TempDir(), "memory.pressure")
	for text, want := range map[string]float64{
		"some avg10=1.50 avg60=12.25 avg300=0.00 total=1\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n": 12.25,
		"some avg10=3.00 avg60=0.50 avg300=9.00 total=1\n":                                                  3,
	} {
		os.WriteFile(path, []byte(text), 0o644)
		if got, ok := pressure(path); !ok || got != want {
			t.Errorf("%q: got %v %v", text, got, ok)
		}
	}
	os.WriteFile(path, []byte("full avg10=50.00 avg60=50.00 avg300=50.00 total=1\n"), 0o644)
	if _, ok := pressure(path); ok {
		t.Error("a file saying no `some` stalls read as one")
	}
}
