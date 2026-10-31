package config

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

const launch = `[launch]
seat = ["acme", "{conversation}", "--model", "{model}", "{pins}", "{off}"]
pins = "--pin"
off = ["A=1", "{model}"]
typo = ["{nothing}"]
odd = ["{first}"]
first = true

[account]
env = "ACME_HOME"
usual = "~/.acme"
home = "~/.acme-{account}"
drop = "~/.acme-*"
unset = ["ACME_KEY"]
`

// manifest is acme's, its [launch] holding extra too.
func manifest(t *testing.T, extra string) {
	adapters := t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	text := strings.Replace(launch, "[launch]\n", "[launch]\n"+extra, 1)
	if err := os.WriteFile(filepath.Join(adapters, "acme.toml"), []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
}

// A placeholder is the call's words, else the table's own key's, a string one word; a name
// neither gives, or a key holding no words, is refused rather than dropped.
func TestLaunchPutsTheCallsWordsOrTheTablesInEachPlaceholder(t *testing.T) {
	manifest(t, "")
	call := map[string][]string{"conversation": nil, "model": {"m 1"}}
	if got, ok, err := Launch("acme", "seat", call); !ok || err != nil ||
		!slices.Equal(got, []string{"acme", "--model", "m 1", "--pin", "A=1", "m 1"}) {
		t.Fatalf("Words = %q %v %v", got, ok, err)
	}
	for _, key := range []string{"typo", "odd"} {
		if _, ok, err := Launch("acme", key, call); ok || err == nil {
			t.Errorf("%s: not refused", key)
		}
	}
	if _, ok, err := Launch("acme", "turn", call); ok || err != nil {
		t.Errorf("a key the table lacks: %v %v", ok, err)
	}
}

// A call on an account runs on its home with the usual login's credentials gone; one naming no
// account drops an account's home handed down, and keeps any other.
func TestALoginsEnvironment(t *testing.T) {
	manifest(t, "")
	home := t.TempDir()
	t.Setenv("HOME", home)
	for _, each := range []struct {
		account, handed string
		want            []string
	}{
		{"be", home + "/.acme-ce", []string{"PATH=/bin", "ACME_HOME=" + home + "/.acme-be"}},
		{"", home + "/.acme-ce", []string{"PATH=/bin", "ACME_KEY=k"}},
		{"", "/own", []string{"PATH=/bin", "ACME_KEY=k", "ACME_HOME=/own"}},
	} {
		t.Setenv("AGENTKIT_ACCOUNT", each.account)
		t.Setenv("ACME_HOME", each.handed)
		login, ok, err := Account("acme")
		if !ok || err != nil {
			t.Fatal(ok, err)
		}
		got := login.Environ([]string{"PATH=/bin", "ACME_KEY=k", "ACME_HOME=" + each.handed})
		if !slices.Equal(got, each.want) {
			t.Errorf("%+v: %q", each, got)
		}
	}
}

// The usual login a named one shares is the one a seat on the usual login runs on: the caller's
// own home, unless that seat's line unsets the variable naming it.
func TestTheUsualLoginIsTheOneAUsualSeatRunsOn(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("ACME_HOME", "/own")
	for extra, want := range map[string]string{"": "/own", `env = ["-u", "ACME_HOME"]` + "\n": home + "/.acme"} {
		manifest(t, extra)
		if login, _, err := Account("acme"); login.Usual != want || err != nil {
			t.Errorf("%q: usual %q, %v", extra, login.Usual, err)
		}
	}
}
