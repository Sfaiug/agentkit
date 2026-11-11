package helper

import (
	"os"
	"os/exec"
	"runtime"
	"testing"
)

// A piece there is handed in its command what one here is handed in its environment, byte for
// byte: AK_TIMES and the tests AK_ONLY lists.
func TestAPieceThereIsHandedTimesAndTests(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the piece's line is bash's")
	}
	clone, times := t.TempDir(), `{"t/it's.sh": 1.5}`
	t.Setenv("HOME", t.TempDir())
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	for _, args := range [][]string{{"init", "-q", clone},
		{"-C", clone, "-c", "user.name=Ada", "-c", "user.email=ada@example.com", "commit", "-q", "--allow-empty", "-m", "first"}} {
		if said, err := exec.Command("git", args...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, said)
		}
	}
	line := pinned(`printf '%s\n---\n' "$AK_TIMES"; cat "$AK_ONLY"`, times, []string{"t/a b.sh", "t/c'd.sh"})
	cmd := exec.Command("bash", "-c", line)
	cmd.Dir, cmd.Env = clone, []string{"PATH=" + os.Getenv("PATH"), "HOME=" + os.Getenv("HOME"), "GIT_CONFIG_NOSYSTEM=1"}
	said, err := cmd.CombinedOutput()
	if want := times + "\n---\nt/a b.sh\nt/c'd.sh\n"; err != nil || string(said) != want {
		t.Fatalf("the piece was handed %q (%v), want %q", said, err, want)
	}
}
