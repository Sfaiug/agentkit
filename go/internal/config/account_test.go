package config

import (
	"os"
	"path/filepath"
	"testing"
)

const accounts = `[account]
env = "ACME_HOME"
usual = "~/.acme"
home = "~/.acme-{account}"
drop = "~/.acme-*"

[hooks.install]
settings = "{home}/hooks.json"

[hooks.install.events]
Stop = ["a.sh"]
`

// A table's file is under the account's home, else the variable's unless it is an account's,
// else the usual one, each spelled as the adapter's shell spells it.
func TestTheLoginHomeIsAnAccountsTheVariablesOrTheUsual(t *testing.T) {
	adapters := t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	if err := os.WriteFile(filepath.Join(adapters, "acme.toml"), []byte(accounts), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, each := range []struct{ home, account, variable, want string }{
		{"/h", "", "", "/h/.acme"},
		{"/h", "", "/elsewhere", "/elsewhere"},
		{"/h", "be", "/elsewhere", "/h/.acme-be"},
		{"/h", "", "/h/.acme-ce/deeper", "/h/.acme"}, // `*` is any text, slashes included
		{"/h*", "", "/hx/.acme-ce", "/hx/.acme-ce"},  // and a `*` in the home's own name none
		{"/h/", "", "", "/h//.acme"},                 // joined as text, never cleaned
	} {
		t.Setenv("HOME", each.home)
		t.Setenv("USERPROFILE", each.home)
		t.Setenv("AGENTKIT_ACCOUNT", each.account)
		t.Setenv("ACME_HOME", each.variable)
		table, ok, err := Hooks("acme")
		if want := each.want + string(filepath.Separator) + "hooks.json"; err != nil || !ok || table.Settings != want || table.File {
			t.Errorf("%+v: %+v %v %v, want %s", each, table, ok, err, want)
		}
	}
}
