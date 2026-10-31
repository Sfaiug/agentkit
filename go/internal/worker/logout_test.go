package worker

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLogoutWordsSplitBetweenTwoLooksAreFoundAsTheManifestSpellsThem(t *testing.T) {
	adapters, out := t.TempDir(), t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	manifest := "version = 1\n[auth]\nsignatures = [\"\", \"Please log in again.\"]\n"
	if err := os.WriteFile(filepath.Join(adapters, "acme.toml"), []byte(manifest), 0o600); err != nil {
		t.Fatal(err)
	}
	log, err := os.Create(filepath.Join(out, "stderr.log"))
	if err != nil {
		t.Fatal(err)
	}
	defer log.Close()
	words := loggedOut("acme", out)
	for _, said := range []string{"acme 1.0\n", "token refused; PLEASE LOG", " IN AGAIN.\nunwinding\n"} {
		if found := words.seen(); found != "" {
			t.Fatalf("found %q before it was said", found)
		}
		log.WriteString(said)
	}
	if found := words.seen(); found != "Please log in again." {
		t.Fatalf("found %q", found)
	}
}
