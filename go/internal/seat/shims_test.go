package seat

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

// Every link lands on the body, and the program beside it on this one, whatever was there before.
func TestShimsTakeTheirPlaces(t *testing.T) {
	home := sandbox(t)
	own := filepath.Join(home, ".agentkit", "shim")
	bin := filepath.Join(home, ".agentkit", "bin")
	if err := os.MkdirAll(bin, 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(home, "moved", "tools", "tmux-shim"), filepath.Join(bin, "tmux")); err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(bin, "gh"), "a file where a link goes")
	write(t, filepath.Join(home, "other"), "")
	if err := os.Symlink(filepath.Join(home, "other"), filepath.Join(bin, "git")); err != nil {
		t.Fatal(err)
	}
	for range 2 { // and an opening after that changes nothing
		dir, err := shims()
		if err != nil || dir != bin {
			t.Fatalf("%q, %v", dir, err)
		}
		for _, name := range shimmed {
			at, err := filepath.EvalSymlinks(filepath.Join(bin, name))
			if want, _ := filepath.EvalSymlinks(filepath.Join(own, "shim")); err != nil || at != want {
				t.Errorf("%s leads to %q: %v", name, at, err)
			}
		}
		program, _ := os.Executable()
		program, _ = filepath.EvalSymlinks(program)
		if at, err := filepath.EvalSymlinks(filepath.Join(own, "ak")); err != nil || at != program {
			t.Errorf("the program beside it is %q, not %q: %v", at, program, err)
		}
		info, err := os.Stat(filepath.Join(own, "shim"))
		if err != nil || info.Mode().Perm()&0o100 == 0 {
			t.Errorf("the body cannot run: %v %v", info, err)
		}
		left, _ := os.ReadDir(own)
		names := []string{}
		for _, entry := range left {
			names = append(names, entry.Name())
		}
		if !slices.Equal(names, []string{"ak", "shim"}) {
			t.Errorf("its folder holds %q", names)
		}
	}
}
