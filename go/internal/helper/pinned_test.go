package helper

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
)

// A piece there is handed in its command what one here is handed in its environment, byte for
// byte: AK_TIMES, the paths of the file AK_CHANGED names, a first one starting with a space, and
// the tests AK_ONLY lists.
func TestAPieceThereIsHandedTimesPathsAndTests(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the piece's line is bash's")
	}
	clone, changed := t.TempDir(), filepath.Join(t.TempDir(), "changed")
	times, paths := `{"t/it's.sh": 1.5}`, " widget.txt\nretry.txt\n"
	if err := os.WriteFile(changed, []byte(paths), 0o666); err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", t.TempDir())
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	for _, args := range [][]string{{"init", "-q", clone},
		{"-C", clone, "-c", "user.name=Ada", "-c", "user.email=ada@example.com", "commit", "-q", "--allow-empty", "-m", "first"}} {
		if said, err := exec.Command("git", args...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, said)
		}
	}
	line, err := pinned(`printf '%s\n---\n' "$AK_TIMES"; cat "$AK_CHANGED"; echo ---; cat "$AK_ONLY"`, times, changed, []string{"t/a b.sh", "t/c'd.sh"})
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("bash", "-c", line)
	cmd.Dir, cmd.Env = clone, []string{"PATH=" + os.Getenv("PATH"), "HOME=" + os.Getenv("HOME"), "GIT_CONFIG_NOSYSTEM=1"}
	said, err := cmd.CombinedOutput()
	if want := times + "\n---\n" + paths + "---\nt/a b.sh\nt/c'd.sh\n"; err != nil || string(said) != want {
		t.Fatalf("the piece was handed %q (%v), want %q", said, err, want)
	}
}
