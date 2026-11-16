package config

import (
	"os"
	"path/filepath"
	"testing"
)

// Only a row the table gives no label is named off its id: a label, even the id itself, wins.
func TestALabelTheTableGivesWinsEvenWhereItIsTheID(t *testing.T) {
	dir := t.TempDir()
	manifest := "family = \"Acme\"\n[catalog]\n\"acme-nova-7-1\" = { label = \"acme-nova-7-1\" }\n\"acme-nova-7-2\" = {}\n"
	if err := os.WriteFile(filepath.Join(dir, "acme.toml"), []byte(manifest), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv(adapterDir, dir)
	for id, want := range map[string]string{"acme-nova-7-1": "acme-nova-7-1", "acme-nova-7-2": "Nova 7.2"} {
		if got := ModelName("nova", map[string]Model{"nova": {Harness: "acme", ID: id}}); got != want {
			t.Errorf("%s: %q, not %q", id, got, want)
		}
	}
}

// A harness runs other makers' models too: each is said without its own maker's family word,
// whichever harness runs it, as a board's release is.
func TestAModelIsSaidWithoutItsMakersFamilyWordWhicheverHarnessRunsIt(t *testing.T) {
	dir := t.TempDir()
	for name, family := range map[string]string{"acme": "Acme", "zeta": "Zeta"} {
		if err := os.WriteFile(filepath.Join(dir, name+".toml"), []byte("family = \""+family+"\"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv(adapterDir, dir)
	if got := ModelLabel("zeta", "acme/acme-nova-7-1", ""); got != "Nova 7.1" {
		t.Errorf("ModelLabel: %q, not Nova 7.1", got)
	}
	if got := Spoken("Acme Nova 7.1"); got != "Nova 7.1" {
		t.Errorf("Spoken: %q, not Nova 7.1", got)
	}
}
