package usage

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A provider listing accounts is the one a worker turn runs on next: another account with room
// before the usual login, and the usual one once every other is spent.
func TestAnotherAccountWithRoomGoesBeforeTheUsualLogin(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	os.MkdirAll(filepath.Join(home, ".agentkit"), 0o700)
	config := "[defaults]\norchestrator = \"fable\"\nworkers = [\"fable\"]\n\n[models.fable]\nharness = \"claude\"\nmodel = \"fable\"\neffort = \"high\"\nprovider = \"anthropic\"\n\n[providers.anthropic]\nmode = \"subscription\"\naccounts = [\"default\", \"two\", \"three\"]\n"
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	week := func(used float64) *run.Object {
		return fields("meters", []any{fields("name", "weekly", "used", used, "window_secs", 604800.0, "resets_at", clock()+86400)})
	}
	for _, each := range []struct {
		two, three float64
		want       string
	}{{40, 20, "three"}, {100, 100, "default"}} {
		prov := fields("accounts", fields("default", week(10), "two", week(each.two), "three", week(each.three), "gone", week(0)))
		flagAccounts("anthropic", prov, clock(), nil)
		if prov.Str("account") != each.want || len(prov.Dict("accounts").Keys()) != 3 {
			t.Errorf("%v: on %q of %v", each, prov.Str("account"), prov.Dict("accounts").Keys())
		}
	}
}
