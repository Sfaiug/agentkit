//go:build unix

package gh

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// fake puts a gh running script first on PATH, none where script is empty.
func fake(t *testing.T, script string) {
	t.Helper()
	bin := t.TempDir()
	t.Setenv("PATH", bin)
	if script == "" {
		return
	}
	if err := os.WriteFile(filepath.Join(bin, "gh"), []byte("#!/bin/sh\n"+script+"\n"), 0o700); err != nil {
		t.Fatal(err)
	}
}

// The reason a failing gh gives is what Python's gh_json gives: gh's own words, stdout first,
// its line endings as Python reads them, stripped and cut at 300 characters; else why gh did
// not start, or that it printed no JSON.
func TestJSONSaysWhyGhFailedAsPythonSaysIt(t *testing.T) {
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	long := strings.Repeat("é", 400)
	for script, want := range map[string]string{
		`printf ' said\r'; printf '\nto stderr \n' >&2; exit 4`: "said\n\nto stderr",
		"printf " + long + "; exit 1":                           strings.Repeat("é", 300),
		"printf 'not json'":                                     "gh printed no JSON (Expecting value: line 1 column 1 (char 0))",
		"":                                                      "gh: [Errno 2] No such file or directory: 'gh'",
	} {
		fake(t, script)
		if value, why, err := JSON(t.TempDir(), "api", "user"); value != nil || why != want || err != nil {
			t.Errorf("%.30q: %v %q %v, want %q", script, value, why, err, want)
		}
	}
}

// gh is found as Python's subprocess finds it: a relative PATH entry is read from the folder gh
// runs in, and the last entry, under no folder, says why none holds a gh.
func TestJSONFindsGhAsPythonDoes(t *testing.T) {
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	fake(t, `printf '{"login": "acme"}'`)
	dir := t.TempDir()
	if err := os.Rename(filepath.Join(os.Getenv("PATH"), "gh"), filepath.Join(dir, "gh")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", ".")
	value, why, err := JSON(dir, "api", "user")
	if user, _ := value.(*run.Object); user == nil || user.Str("login") != "acme" || why != "" || err != nil {
		t.Fatalf("%v %q %v", value, why, err)
	}
	t.Setenv("PATH", filepath.Join(dir, "gh"))
	if _, why, err := JSON(dir, "api", "user"); why != "gh: [Errno 20] Not a directory: 'gh'" || err != nil {
		t.Fatalf("%q %v", why, err)
	}
}

// A gh that is not executable, and bytes that are no UTF-8, Python says its own way, so Go
// leaves the call to it.
func TestJSONLeavesToPythonWhatItCannotSayAsPythonDoes(t *testing.T) {
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	fake(t, `printf 'bad \377' >&2; exit 1`)
	if _, _, err := JSON(t.TempDir(), "api", "user"); !errors.Is(err, ErrPython) {
		t.Fatalf("no text: answered %v", err)
	}
	if err := os.Chmod(filepath.Join(os.Getenv("PATH"), "gh"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := JSON(t.TempDir(), "api", "user"); !errors.Is(err, ErrPython) {
		t.Fatalf("not executable: answered %v", err)
	}
}
