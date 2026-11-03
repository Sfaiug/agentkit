package seat

import (
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
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

// What the shim does with each answer the program beside it gives, or fails to.
func TestAShimFailsOpen(t *testing.T) {
	home := t.TempDir()
	write(t, filepath.Join(home, "real", "tmux"), "#!/bin/sh\nfor each in \"$@\"; do printf '<%s>' \"$each\"; done\n")
	body := filepath.Join(home, "own", "shim")
	write(t, body, string(shimBody))
	for _, each := range []string{body, filepath.Join(home, "real", "tmux")} {
		if err := os.Chmod(each, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	shim := filepath.Join(home, "bin", "tmux")
	if err := os.MkdirAll(filepath.Dir(shim), 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(body, shim); err != nil {
		t.Fatal(err)
	}
	asIs := "<new-window><a b>"
	for _, each := range []struct {
		name, program, out, err string
		code                    int
	}{
		{"no program", "", asIs, "", 0},
		{"one with no loader", "#!" + filepath.Join(home, "removed") + "\n", asIs, "", 0},
		{"one that is no program", "\x7fELF", asIs, "", 0},
		{"one that dies", "#!/bin/sh\necho half\nkill -KILL $$\n", asIs, "", 0},
		{"one that fails", "#!/bin/sh\necho half\nexit 2\n", asIs, "", 0},
		{"one that fails saying nothing", "#!/bin/sh\necho oops >&2\nexit 1\n", asIs, "", 0},
		{"one with nothing to change", "#!/bin/sh\nexit 0\n", asIs, "", 0},
		{"a refusal", "#!/bin/sh\necho no way\nexit 1\n", "", "no way\n", 1},
		{"new arguments", "#!/bin/sh\necho \"new -e 'a b' 'it'\\''s;' '\\$HOME'\"\n", "", "", 0},
	} {
		t.Run(each.name, func(t *testing.T) {
			program := filepath.Join(home, "own", "ak")
			os.Remove(program)
			if each.program != "" {
				write(t, program, each.program)
				if err := os.Chmod(program, 0o755); err != nil {
					t.Fatal(err)
				}
			}
			call := exec.Command(shim, "new-window", "a b")
			call.Env = []string{"AGENTKIT_SESSION=acme", "PATH=" + filepath.Dir(shim) + ":" + filepath.Join(home, "real") + ":/usr/bin:/bin"}
			var out, errOut strings.Builder
			call.Stdout, call.Stderr = &out, &errOut
			err := call.Run()
			want := each.out
			if each.name == "new arguments" {
				want = "<new><-e><a b><it's;><$HOME>"
			}
			if code := call.ProcessState.ExitCode(); code != each.code || out.String() != want || errOut.String() != each.err {
				t.Errorf("exit %d (%v), %q, %q", code, err, out.String(), errOut.String())
			}
		})
	}
}
