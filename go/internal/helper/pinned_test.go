package helper

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// A piece there is handed in files what one here is handed, byte for byte: the record AK_TIMES
// names, past what one argument holds, and the tests AK_ONLY lists, each read from the file of
// the parcel piece.sh names in that variable.
func TestAPieceThereIsHandedTimesAndTests(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the piece's line is bash's")
	}
	clone, in := t.TempDir(), t.TempDir()
	times := `{"t/it's.sh": 1.5` + strings.Repeat(`, "t/part.sh::x": 1.0`, maxArg/20) + "}"
	t.Setenv("HOME", t.TempDir())
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	for _, args := range [][]string{{"init", "-q", clone},
		{"-C", clone, "-c", "user.name=Ada", "-c", "user.email=ada@example.com", "commit", "-q", "--allow-empty", "-m", "first"}} {
		if said, err := exec.Command("git", args...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, said)
		}
	}
	line, files := pinned(`cat "$AK_TIMES"; echo ---; cat "$AK_ONLY"`, times, []string{"t/a b.sh", "t/c'd.sh"})
	cmd := exec.Command("bash", "-c", line)
	cmd.Dir, cmd.Env = clone, []string{"PATH=" + os.Getenv("PATH"), "HOME=" + os.Getenv("HOME"), "GIT_CONFIG_NOSYSTEM=1"}
	for name, handed := range files {
		if err := os.WriteFile(filepath.Join(in, name), handed.data, 0o644); err != nil {
			t.Fatal(err)
		}
		cmd.Env = append(cmd.Env, name+"="+filepath.Join(in, name))
	}
	said, err := cmd.CombinedOutput()
	if want := times + "---\nt/a b.sh\nt/c'd.sh\n"; err != nil || string(said) != want {
		t.Fatalf("the piece was handed %.200q (%v), want %.200q", said, err, want)
	}
}
