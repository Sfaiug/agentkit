package usage

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A worker turn's login ranks on what its model reads there, as Python's usage._worker_rank: a cap
// only another model watches neither spends the login, puts it on credits nor cuts its budget, and
// a login whose meters read is no unknown one for lacking a week; the model's own week still does.
func TestATurnsLoginRanksOnWhatItsModelReadsThere(t *testing.T) {
	for _, each := range []struct {
		name, other, want      string
		week, scoped, credits  float64 // the first login's
		otherWeek, otherScoped float64
		sessionOnly            bool
	}{
		{name: "another model's spent cap", other: "default", want: "first", week: 10, scoped: 100, otherWeek: 30, otherScoped: 10},
		{name: "another model's credits", other: "second", want: "first", week: 10, scoped: 100, credits: 10, otherWeek: 50},
		{name: "another model's budget", other: "second", want: "first", week: 10, scoped: 90, otherWeek: 50},
		{name: "a session read without a week", other: "default", want: "first", sessionOnly: true, otherWeek: 30},
		{name: "its own spent week", other: "second", want: "second", week: 100, otherWeek: 10, otherScoped: 100},
	} {
		t.Run(each.name, func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("HOME", home)
			t.Setenv("USERPROFILE", home)
			t.Setenv("AGENTKIT_SESSION", "")
			adapters := filepath.Join(home, "adapters")
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			now := clock()
			reading := func(week, scoped, credits float64) *run.Object {
				return fields("resets", 0, "credits", credits, "meters", []any{
					fields("name", "weekly_all", "used", week, "window_secs", 604800, "resets_at", now+86400),
					fields("name", "weekly_scoped", "used", scoped, "window_secs", 604800, "resets_at", now+86400)})
			}
			first := reading(each.week, each.scoped, each.credits)
			if each.sessionOnly {
				first = fields("resets", 0, "meters", []any{fields("name", "session", "used", 10, "window_secs", 18000, "resets_at", now+3600)})
			}
			for path, data := range map[string]string{
				filepath.Join(home, ".agentkit", "config.toml"): "[models.alpha]\nharness='acme'\nmodel='alpha'\neffort='high'\nprovider='acme'\nmeter='weekly_scoped'\n" +
					"[models.beta]\nharness='acme'\nmodel='beta'\neffort='high'\nprovider='acme'\n[providers.acme]\nmode='subscription'\naccounts=['first','" + each.other + "']\n",
				filepath.Join(adapters, "acme.toml"): "version = 1\n",
				filepath.Join(adapters, "acme.sh"):   "#!/bin/sh\nexit 0\n",
				filepath.Join(state(), "usage.json"): run.Line(fields("fetched_at", now, "providers", fields("acme", fields("resets", 0,
					"accounts", fields("first", first, each.other, reading(each.otherWeek, each.otherScoped, 0)))))),
			} {
				if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte(data), 0o700); err != nil {
					t.Fatal(err)
				}
			}
			if account, room, err := TurnAccount("beta", ""); err != nil || account != each.want || !room {
				t.Fatalf("beta's turn runs on %q (room %v, %v), want %q", account, room, err, each.want)
			}
		})
	}
}
