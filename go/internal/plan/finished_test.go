package plan

import "testing"

// A line is a box, and open, as Python's plan.BOX and plan.is_open read it: its whitespace and
// word edges Unicode's.
func TestALineReadsAsPythonReadsIt(t *testing.T) {
	for line, want := range map[string][2]bool{ // boxed, open
		"\u00a0- [x] Fix the api":      {true, false},
		"-\u00a0[ ] Deploy the api":    {true, true},
		"- [x](https://example.com) y": {false, false},
		"- [x] y ·\u00a0done by hand":  {true, true},
		"- [x] écheck: y":              {true, false},
		"- [x] y · doneé":              {true, false},
	} {
		if got := [2]bool{boxed(line), open(line)}; got != want {
			t.Errorf("%q: boxed, open = %v, want %v", line, got, want)
		}
	}
}
