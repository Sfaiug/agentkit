//go:build unix

package tick

import (
	"io"
	"path/filepath"
	"testing"
)

func TestSavedForeignPRHandsOverAfterSearchDropsIt(t *testing.T) {
	ak, _ := idleHome(t, answers)
	path := filepath.Join(ak, "runs", "fix-api", "run.json")
	text := `{"state":"pass","foreign":true,"pr":"https://github.com/other/api/pull/1","handed_back":true,"reported":true,"tree_stopped":[null,null]}`
	put(t, path, text)
	if carries(io.Discard, io.Discard) {
		t.Fatal("saved foreign PR was lost when the open search returned nothing")
	}
	if read(t, path) != text {
		t.Fatal("handover changed the settled run")
	}
}
