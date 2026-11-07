package seat

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestWorkingSeatsGoInTheReadingListingsOrder(t *testing.T) {
	home := sandbox(t)
	for _, project := range []string{"alpha", "zulu"} {
		if err := os.MkdirAll(filepath.Join(home, "code", project, ".git"), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	// acme's record names no repo, which its run's would file under alpha, ahead of zulu
	record(t, home, "acme", nil)
	record(t, home, "beta", map[string]any{"repo": filepath.Join(home, "code", "zulu")})
	runRecord(t, home, "r-acme", map[string]any{"state": "running", "repo": filepath.Join(home, "code", "alpha")})
	runRecord(t, home, "r-beta", map[string]any{"state": "running", "launched_session": "beta"})
	working, known := Working(moment)
	if want := []string{"beta", "acme"}; !known || !reflect.DeepEqual(working, want) {
		t.Fatalf("Working = %v, %v; want %v, true", working, known, want)
	}
}
