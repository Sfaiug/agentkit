package plan

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestAFrameFollowsTheRenamesOnceAndWhatComesAfterItFollowsThemAgain(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	write := func(name, record string) {
		if os.MkdirAll(state, 0o700) != nil || os.WriteFile(filepath.Join(state, "session-"+name+".json"), []byte(record), 0o600) != nil {
			t.Fatal(name)
		}
	}
	write("ash", `{}`)
	write("elm", `{"renamed": "ash"}`)
	frame := OneLook()
	if got := frame.Names("ash"); !slices.Equal(got, []string{"ash", "elm"}) {
		t.Fatalf("the frame's first lookup: %q", got)
	}
	write("oak", `{"renamed": "ash"}`)
	if got := frame.Names("ash"); !slices.Equal(got, []string{"ash", "elm"}) {
		t.Errorf("the rest of the frame: %q", got)
	}
	if got := Names("ash"); !slices.Equal(got, []string{"ash", "elm", "oak"}) {
		t.Errorf("a writer: %q", got)
	}
	if got := OneLook().Names("ash"); !slices.Equal(got, []string{"ash", "elm", "oak"}) {
		t.Errorf("the next frame: %q", got)
	}
}
