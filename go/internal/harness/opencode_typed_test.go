package harness

import (
	"path/filepath"
	"testing"
)

func TestOpenCodeTypedIsEachUserRowsTextDatedInSeconds(t *testing.T) {
	database, err := filepath.Abs(filepath.Join("testdata", "opencode.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("OPENCODE_DB", database)
	if typed := opencodeTyped("ses_Free"); len(typed) != 1 || typed[0] != (Prompt{0.998, "Rename the acme report."}) {
		t.Fatalf("typed %v", typed)
	}
	t.Setenv("OPENCODE_DB", filepath.Join(t.TempDir(), "opencode.db"))
	if typed := opencodeTyped("ses_Free"); typed != nil {
		t.Fatalf("typed %v with no database", typed)
	}
}
