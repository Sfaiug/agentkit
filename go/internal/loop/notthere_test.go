package loop

import "testing"

// A run of just the listed tests passes what its tree holds as Python's gate.passes_what_it_holds
// reads it: a test named as not there is passed, one there must be named as run, and a failing run
// passes only where it ended as its runner ends, one at least was not there and nothing else failed.
func TestARunPassesWhatItsTreeHolds(t *testing.T) {
	only := []string{"a", "b"}
	for _, c := range []struct {
		name                string
		code                int
		ran, failed, absent []string
		want                bool
	}{
		{"each run, passing", 0, only, nil, nil, true},
		{"one not there, the other run", 0, []string{"a"}, nil, []string{"b"}, true},
		{"none there", 0, nil, nil, only, true},
		{"one neither run nor not there", 0, []string{"a"}, nil, nil, false},
		{"failing, one not there, the other passed", 1, []string{"a"}, nil, []string{"b"}, true},
		{"failing, one not there, the other failed", 1, []string{"a"}, []string{"a"}, []string{"b"}, false},
		{"failing, one not there and named as failed too", 1, []string{"a"}, []string{"b"}, []string{"b"}, true},
		{"failing, one not there, a part of the other failed", 1, []string{"a"}, []string{"a::part"}, []string{"b"}, false},
		{"failing, each there", 1, only, nil, nil, false},
		{"dead by a signal", -1, []string{"a"}, nil, []string{"b"}, false},
		{"one not there, the other dead by a signal and its runner with it", 143, []string{"a"}, nil, []string{"b"}, false},
	} {
		if got := passesWhatItHolds(c.code, only, c.ran, c.failed, c.absent); got != c.want {
			t.Errorf("%s: passed %v, want %v", c.name, got, c.want)
		}
	}
}
