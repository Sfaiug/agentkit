package usage

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAccountOrderUsesThisModelsMetersAndWindowsBeforeCredits(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	config := `[models.opus]
harness='claude'
model='claude-opus'
effort='xhigh'
provider='test'
meter='weekly_opus'
[models.fable]
harness='claude'
model='claude-fable'
effort='xhigh'
provider='test'
meter='weekly_fable'
[providers.test]
mode='subscription'
accounts=['default','second']
`
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	now := clock()
	reading := func(session, opus, fable, credits float64) *run.Object {
		return fields("credits", credits, "meters", []any{
			fields("name", "session", "used", session, "window_secs", 18000, "resets_at", now+3600),
			fields("name", "weekly_opus", "used", opus, "window_secs", 604800, "resets_at", now+86400),
			fields("name", "weekly_fable", "used", fable, "window_secs", 604800, "resets_at", now+86400)})
	}
	for _, each := range []struct {
		name          string
		first, second *run.Object
		want          string
		spent         bool
	}{
		{"another model is spent", reading(10, 10, 100, 0), reading(10, 20, 0, 0), "default", false},
		{"low home", reading(97, 10, 0, 0), reading(10, 20, 0, 0), "second", false},
		{"credits wait behind windows", reading(100, 10, 0, 10), reading(10, 20, 0, 0), "second", false},
		{"own cap is spent", reading(10, 100, 0, 0), reading(10, 20, 0, 0), "second", true},
	} {
		t.Run(each.name, func(t *testing.T) {
			path := filepath.Join(state(), "usage.json")
			data := run.Line(fields("fetched_at", now, "providers", fields("test", fields("accounts", fields("default", each.first, "second", each.second)))))
			if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
				t.Fatal(err)
			}
			accounts, err := SeatAccounts("opus", "default")
			if err != nil || len(accounts) != 2 || accounts[0].Name != each.want {
				t.Fatal(accounts, err)
			}
			for _, a := range accounts {
				if a.Name == "default" && (a.Spent != "") != each.spent {
					t.Fatal(accounts)
				}
			}
			kept, _ := os.ReadFile(path)
			if string(kept) != data {
				t.Fatal("ranking wrote the snapshot")
			}
		})
	}
	// a stale snapshot ranks nothing: each account is asked again, as seat_account's collect asks,
	// and its old reading of a low home would put the other account first
	adapters := filepath.Join(home, "adapters")
	if err := os.MkdirAll(adapters, 0o700); err != nil {
		t.Fatal(err)
	}
	for account, used := range map[string]float64{"default": 10, "second": 50} {
		answer := run.Line(fields("provider", "test", "meters", reading(used, 10, 0, 0).Get("meters")))
		if err := os.WriteFile(filepath.Join(adapters, account+".json"), []byte(answer), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	script := "#!/bin/sh\n[ \"$1\" = usage ] && exec cat \"$(dirname \"$0\")/${AGENTKIT_ACCOUNT:-default}.json\"\nexit 1\n"
	if err := os.WriteFile(filepath.Join(adapters, "claude.sh"), []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	stale := run.Line(fields("fetched_at", now-600, "providers", fields("test", fields("accounts",
		fields("default", reading(97, 10, 0, 0), "second", reading(10, 20, 0, 0))))))
	if err := os.WriteFile(filepath.Join(state(), "usage.json"), []byte(stale), 0o600); err != nil {
		t.Fatal(err)
	}
	if accounts, err := SeatAccounts("opus", "default"); err != nil || len(accounts) != 2 || accounts[0].Name != "default" {
		t.Fatal("stale account meters were used", accounts, err)
	}
	missing := run.Line(fields("fetched_at", now, "providers", fields("test", fields("accounts", fields("default", reading(97, 10, 0, 0))))))
	if err := os.WriteFile(filepath.Join(state(), "usage.json"), []byte(missing), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := SeatAccounts("opus", "default"); !errors.Is(err, ErrPython) {
		t.Fatal("an added account was not handed over for fresh meters", err)
	}
}
