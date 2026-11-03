package host

import (
	"os"
	"path/filepath"
	"testing"
)

// MemoryMax reads as systemd writes it, the last file naming it winning: bytes bare, 1024-based
// suffixes in either case, a share of MemTotal, and `infinity` for no ceiling.
func TestTheLastDropInNamingMemoryMaxWins(t *testing.T) {
	total, known := memTotalMB()
	for _, c := range []struct {
		files []string
		want  int
		set   bool
	}{
		{[]string{"MemoryMax=10G\n"}, 10240, true},
		{[]string{"MemoryMax = 2147483648\n", "MemoryMax=512m\n"}, 512, true},
		{[]string{"MemoryMax=1048576K\n"}, 1024, true},
		{[]string{"MemoryMax=10G\n", "MemoryMax=infinity\n"}, 0, false},
		{[]string{"MemoryMax=10G\n", "MemoryMax=lots\n"}, 10240, true},
		{[]string{"MemoryMax=50%\n"}, total / 2, known},
		{[]string{"TasksMax=100\n"}, 0, false},
	} {
		t.Setenv("XDG_CONFIG_HOME", t.TempDir())
		dir := filepath.Join(os.Getenv("XDG_CONFIG_HOME"), "systemd/user/acme.slice.d")
		os.MkdirAll(dir, 0o755)
		for i, text := range c.files {
			os.WriteFile(filepath.Join(dir, string(rune('a'+i))+".conf"), []byte("[Slice]\n"+text), 0o644)
		}
		if got, set := dropInMemoryMax("acme.slice"); got != c.want || set != c.set {
			t.Errorf("%q: got %d %v", c.files, got, set)
		}
	}
}
