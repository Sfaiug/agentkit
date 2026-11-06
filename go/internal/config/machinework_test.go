package config

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

// A machine takes suites unless its own marks leave tests out, and none does while any table's
// marks are some Python refuses.
func TestAMachineTakesSuitesAsPythonReadsItsMarks(t *testing.T) {
	for _, each := range []struct {
		toml string
		want bool
	}{
		{"suite_helper = 'acme'\n", true},
		{"[machines.acme]\n", true},
		{"[machines.acme]\nwork = ['turns', 'tests']\n", true},
		{"[machines.acme]\nwork = ['turns']\n", false},
		{"[machines.acme]\n[machines.beta]\nwork = ['builds']\n", false},
		{"[machines.acme]\n[google_cloud]\nwork = 'tests'\n", false},
	} {
		home := t.TempDir()
		t.Setenv("HOME", home)
		if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(each.toml), 0o666); err != nil {
			t.Fatal(err)
		}
		if work, known := MachineWork("acme"); (known && slices.Contains(work, "tests")) != each.want {
			t.Errorf("%q: work %v (known %v), want suites %v", each.toml, work, known, each.want)
		}
	}
}
