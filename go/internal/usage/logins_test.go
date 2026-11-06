package usage

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func TestAProviderListingAccountsIsTheOneATurnRunsOnNextAndAHeldResetAddsNothing(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	listed := "[models.echo]\nharness='echo'\nmodel='echo-1'\neffort='high'\nprovider='test'\n" +
		"[providers.test]\nmode='subscription'\naccounts=['default','shoal','reef']\n"
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(listed), 0o600); err != nil {
		t.Fatal(err)
	}
	models, err := config.Models()
	if err != nil {
		t.Fatal(err)
	}
	now := clock()
	week := func(used float64) *run.Object {
		meter := fields("name", "weekly", "used", used, "window_secs", 604800, "resets_at", now+86400)
		return fields("harness", "echo", "meters", []any{meter}, "error", nil, "resets", 2.0)
	}
	for _, each := range []struct {
		name               string
		usual, shoal, reef float64
		want               string
		spent              bool
	}{
		{"another with room before the usual login", 10, 100, 60, "reef", false},
		{"the usual login once no other has room", 50, 100, 100, "default", false},
		{"spent only when every one is", 100, 100, 100, "default", true},
	} {
		t.Run(each.name, func(t *testing.T) {
			accounts := fields("default", week(each.usual), "shoal", week(each.shoal), "reef", week(each.reef))
			prov := gateFlags(fields("test", fields("provider", "test", "accounts", accounts)), now, models).Dict("test")
			if prov.Str("account") != each.want || prov.Truthy("exhausted") != each.spent {
				t.Fatal(run.Line(prov))
			}
			shoal := prov.Dict("accounts").Dict("shoal")
			if !shoal.Truthy("exhausted") || shoal.Get("resets") != run.Float(2) || shoal.Get("headroom") != run.Float(0) || shoal.Get("budget") != run.Float(0) {
				t.Fatal("two resets in hand bought a spent week room", run.Line(shoal))
			}
		})
	}
}
