package usage

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAnEntryOfferedNoMoreStillClaimsItsOwnCap(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	config := `[models.anvil]
harness='claude'
model='anvil-1'
effort='high'
provider='acme'
[models.old]
provider='acme'
meter='weekly_scoped'
[providers.acme]
mode='subscription'
`
	ends := clock() + 86400
	pair := func(model string, moved float64) *run.Object {
		return fields("at", ends-86400, "tokens", 1000, "moved", moved, "resets_at", ends, "prior", 10,
			"model", model, "effort", "high", "run_id", "acme-run", "role", "executor")
	}
	meter := func(name string, used float64) *run.Object {
		return fields("name", name, "used", used, "window_secs", 604800, "resets_at", ends)
	}
	for path, data := range map[string]string{
		filepath.Join(home, ".agentkit", "config.toml"): config,
		filepath.Join(state(), "usage.json"): run.Line(fields("providers", fields("acme", fields(
			"meters", []any{meter("weekly_all", 40), meter("weekly_scoped", 90)})))),
		filepath.Join(state(), pairsFile): run.Line(fields("acme", fields("default", fields(
			"weekly_all", []any{pair("anvil", 1)}, "weekly_scoped", []any{pair("old", 10)})))),
	} {
		if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	r, err := Cached()
	if err != nil {
		t.Fatal(err)
	}
	held, _ := holds("acme", "", r.sharedWeek("acme", object(r.providers.Get("acme"))))
	if tokens, _ := run.Num(held); tokens != 100000 {
		t.Fatal(held)
	}
}
