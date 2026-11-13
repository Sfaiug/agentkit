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
	meter := func(name string, used float64) *run.Object {
		return fields("name", name, "used", used, "window_secs", 604800, "resets_at", ends)
	}
	for path, data := range map[string]string{
		filepath.Join(home, ".agentkit", "config.toml"): config,
		filepath.Join(state(), "usage.json"): run.Line(fields("providers", fields("acme", fields(
			"meters", []any{meter("weekly_all", 40), meter("weekly_scoped", 90)})))),
	} {
		if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	r, err := Cached()
	if err != nil {
		t.Fatal(err)
	}
	if shared := r.sharedWeek("acme", object(r.providers.Get("acme"))); shared.Str("name") != "weekly_all" {
		t.Fatal(run.Line(shared))
	}
}
