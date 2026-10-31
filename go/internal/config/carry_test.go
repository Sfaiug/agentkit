package config

import "testing"

// What a named login's own file holds that the usual one lacks is carried in, tables both hold
// filled in turn, and the whole file is written as Python's share_settings writes it.
func TestCarryWritesWhatPythonWrites(t *testing.T) {
	usual := "top = 1\n[ui]\nvim_mode = false\n"
	own := `name = "ünï \"q\" \\ \t\u0001"
ratio = 0.5
big = 1e20
small = 0.00001
whole = 3.0
list = [1, "a", {x = 1}]
[ui]
vim_mode = true
show = true
[[servers]]
id = "a b"
[nested.deep]
k = 2
"odd key" = -0.0
`
	want := "top = 1\nui = {vim_mode = false, show = true}\nname = \"ünï \\\"q\\\" \\\\ \\t\\u0001\"\n" +
		"ratio = 0.5\nbig = 1e+20\nsmall = 1e-05\nwhole = 3.0\nlist = [1, \"a\", {x = 1}]\n" +
		"servers = [{id = \"a b\"}]\nnested = {deep = {k = 2, \"odd key\" = -0.0}}\n"
	if got, changed, err := Carry(usual, own); got != want || !changed || err != nil {
		t.Fatalf("Carry = %q %v %v, want %q", got, changed, err, want)
	}
}

// A usual file lacking nothing stays as written, and either one not TOML, or a value Go writes
// no TOML for, is refused.
func TestCarryLeavesAFileLackingNothingAndRefusesWhatItCannotWrite(t *testing.T) {
	if got, changed, err := Carry("# mine\n[ui]\nx = 1\n", "[ui]\nx = 2\n"); got != "" || changed || err != nil {
		t.Fatalf("lacking nothing: %q %v %v", got, changed, err)
	}
	for _, each := range [][2]string{{"[bad", "x = 1"}, {"x = 1", "[bad"}, {"", "x = nan"}, {"", "x = 1979-05-27"}} {
		if _, changed, err := Carry(each[0], each[1]); changed || err == nil {
			t.Errorf("Carry(%q, %q) wrote it", each[0], each[1])
		}
	}
}
