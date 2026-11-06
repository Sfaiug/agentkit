//go:build unix

package doctor

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/lock"
)

// A slot queue keeping a seat's name Go cannot keep leaves all of it to Python, which reads it.
func TestASlotQueueGoCannotKeepSaysNothing(t *testing.T) {
	root, _ := home(t, models)
	runs := filepath.Join(root, ".agentkit", "runs")
	os.MkdirAll(runs, 0o700)
	queue := `{"at": 1, "running": 0, "queue": ["urgent-fix", "fix-api"], "turns": [[false, true, true, "acme\udcff", "", 1, []]]}`
	if err := os.WriteFile(filepath.Join(runs, ".slots.queue"), []byte(queue), 0o600); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	if _, read := Report(&out, &errOut); read || out.Len() != 0 || errOut.Len() != 0 {
		t.Fatalf("read=%v stdout=%q stderr=%q", read, out.String(), errOut.String())
	}
}

// A line checker's locked wait holds suite turns under a HOME whose name a glob reads as a pattern.
func TestALandingWaitHoldsUnderAnyHome(t *testing.T) {
	root, _ := home(t, models)
	literal := filepath.Join(root, "acme[work]")
	os.Mkdir(literal, 0o700)
	if err := os.Rename(filepath.Join(root, ".agentkit"), filepath.Join(literal, ".agentkit")); err != nil {
		t.Fatal(err)
	}
	os.Mkdir(filepath.Join(literal, ".agentkit", "runs"), 0o700)
	t.Setenv("HOME", literal)
	t.Setenv("USERPROFILE", literal)
	held, err := lock.Try(filepath.Join(literal, ".agentkit", "runs", ".landing-wait-fixture"))
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	var out, errOut bytes.Buffer
	Report(&out, &errOut)
	if want := "gates  admission never held · suite turns holding now · memory never held\n"; !strings.Contains(out.String(), want) {
		t.Fatalf("no %q in stdout=%q stderr=%q", want, out.String(), errOut.String())
	}
}
