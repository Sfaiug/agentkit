package host

import (
	"os"
	"path/filepath"
	"testing"
)

func TestMemoryIsTightAsPythonsGateReadsIt(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("AK_MIN_FREE_MB", "3072")
	t.Setenv("AK_MAX_RUNS", "")
	none := func() (float64, bool, error) { return 0, false, nil }
	peak := func(mb float64) func() (float64, bool, error) {
		return func() (float64, bool, error) { return mb, true, nil }
	}
	for _, c := range []struct {
		readings string
		peak     func() (float64, bool, error)
		tight    bool
	}{
		{`{"free_mb": 12000}`, none, false},
		{`{"free_mb": 3000}`, none, true},
		{`{"free_mb": 12000, "slice_memory_pressure": 10}`, none, false},
		{`{"free_mb": 12000, "slice_memory_pressure": 10.5}`, none, true},
		// with no run measured, the slice holds runs back past three quarters full
		{`{"free_mb": 12000, "slice_memory_used_mb": 750, "slice_memory_high_mb": 1000}`, none, false},
		{`{"free_mb": 12000, "slice_memory_used_mb": 751, "slice_memory_high_mb": 1000}`, none, true},
		// the runs' swap counts past a quarter of the cap
		{`{"free_mb": 12000, "slice_memory_used_mb": 700, "slice_memory_high_mb": 1000, "runs_memory_swap_mb": 300}`, none, false},
		{`{"free_mb": 12000, "slice_memory_used_mb": 700, "slice_memory_high_mb": 1000, "runs_memory_swap_mb": 301}`, none, true},
		// a measured run needs its peak in the room left
		{`{"free_mb": 12000, "slice_memory_used_mb": 600, "slice_memory_high_mb": 1000}`, peak(400), false},
		{`{"free_mb": 12000, "slice_memory_used_mb": 600, "slice_memory_high_mb": 1000}`, peak(401), true},
		{`{"free_mb": 12000, "unit_limits": [[600, 1000]]}`, peak(401), true},
	} {
		t.Setenv("AK_HOST_READINGS", c.readings)
		if tight, err := MemoryTight(c.peak); err != nil || tight != c.tight {
			t.Errorf("%s: tight %v, %v", c.readings, tight, err)
		}
	}
	t.Setenv("AK_MAX_RUNS", "0")
	if tight, err := MemoryTight(none); tight || err != nil {
		t.Errorf("the tests' AK_MAX_RUNS=0 read memory as tight: %v", err)
	}
}

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
