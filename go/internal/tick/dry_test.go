//go:build unix

package tick

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// A home holding nothing is answered; anything a pass would act on, or a gh logged in, leaves
// the dry run to Python with nothing printed.
func TestDryLeavesToPythonWhatItWouldActOn(t *testing.T) {
	home := t.TempDir()
	bin := t.TempDir()
	for key, value := range map[string]string{
		"HOME": home, "USERPROFILE": home, "TMUX_TMPDIR": t.TempDir(), "AGENTKIT_TMUX_SOCKET": "dry-test",
		"AGENTKIT_SESSION": "", "AGENTKIT_ADAPTER_DIR": "", "PATH": bin + string(os.PathListSeparator) + os.Getenv("PATH"),
	} {
		t.Setenv(key, value)
	}
	gh := func(script string) {
		if err := os.WriteFile(filepath.Join(bin, "gh"), []byte("#!/bin/sh\n"+script+"\n"), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	dry := func(want bool) string {
		t.Helper()
		var out bytes.Buffer
		if Dry(&out) != want || !want && out.Len() > 0 {
			t.Fatalf("answered %v, printing %q", !want, out.String())
		}
		return out.String()
	}
	gh("echo 'To get started, please run:\n\n  gh auth login' >&2; exit 4")
	if got := dry(true); got != "lock free · watch.log 0.0 MB of 5 MB\ngh is not logged in; PR checks skipped (To get started, please run: gh auth login)\n" {
		t.Fatalf("printed %q", got)
	}
	// each a folder holding the file named
	for _, found := range []string{"runs/fix-api", "jobs/fix-api", "secrets/acme", "state/watch.json", "state/notification-outbox/acme.json"} {
		path := filepath.Join(home, ".agentkit", found)
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, nil, 0o600); err != nil {
			t.Fatal(err)
		}
		dry(false)
		if err := os.RemoveAll(filepath.Join(home, ".agentkit")); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AGENTKIT_SESSION", "acme")
	dry(false)
	t.Setenv("AGENTKIT_SESSION", "")
	gh(`echo '{"login": "acme"}'`)
	dry(false)
}
