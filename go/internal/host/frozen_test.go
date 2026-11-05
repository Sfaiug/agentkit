package host

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFreezeIsReadFromTheProcessGroupAndItsAncestors(t *testing.T) {
	for _, group := range []string{"acme/workers", "acme", "", "other"} {
		t.Run(group, func(t *testing.T) {
			root := t.TempDir()
			t.Setenv("AK_CGROUP_ROOT", root)
			path := filepath.Join(root, group, "cgroup.freeze")
			if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
				t.Fatal(err)
			}
			for _, value := range []string{"1\n", "0\n"} {
				if err := os.WriteFile(path, []byte(value), 0o600); err != nil {
					t.Fatal(err)
				}
				if got, want := frozenCgroup("/acme/workers"), group != "other" && value == "1\n"; got != want {
					t.Fatalf("frozen=%v, want %v", got, want)
				}
			}
		})
	}
}
