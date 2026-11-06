package logins

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestALoginEndingSoonSaysWhenAndOneFarOffSaysNothing(t *testing.T) {
	t.Setenv("TZ", "UTC")
	now := time.Date(2026, 10, 24, 12, 0, 0, 0, time.UTC)
	for _, each := range []struct {
		after time.Duration
		email string
		want  string
	}{{2 * time.Hour, "", "login ends Sat 24 Oct 14:00 (today)"},
		{26 * time.Hour, "owner@acme.test", "login owner@acme.test ends Sun 25 Oct 14:00 (tomorrow)"},
		{50 * time.Hour, "", "login ends Mon 26 Oct 14:00 (in 2 days)"},
		{-time.Hour, "", "login ended Sat 24 Oct 11:00"},
		{8 * 24 * time.Hour, "", ""}} {
		login := run.Fields("email", each.email, "ends", float64(now.Add(each.after).Unix()))
		if each.email == "" {
			login.Set("email", nil)
		}
		if got := Ending(login, now); got != each.want {
			t.Errorf("%v from now: %q, want %q", each.after, got, each.want)
		}
	}
	if got := Ending(run.Fields("ends", nil), now); got != "" {
		t.Errorf("no end written down: %q", got)
	}
}

// A login made again keeps what its adapter answers beside the rest, and one that answers nothing
// changes nothing.
func TestARenewedLoginKeepsItsAnswerBesideTheRest(t *testing.T) {
	home, adapters := t.TempDir(), t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	script := "#!/bin/sh\n[ \"$1\" = login-end ] && [ \"$AGENTKIT_ACCOUNT\" = two ] && echo '{\"email\": \"two@acme.test\", \"ends\": null}'\n"
	if err := os.WriteFile(filepath.Join(adapters, "acme.sh"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	state := filepath.Join(home, ".agentkit", "state")
	os.MkdirAll(state, 0o700)
	os.WriteFile(filepath.Join(state, "logins.json"), []byte(`{"acme": {"default": {"email": "owner@acme.test"}, "two": {"ends": 5, "plan": "max"}}}`), 0o600)
	Renewed("acme", "two", "acme")
	Renewed("acme", "", "acme")
	kept, err := run.ReadJSON(filepath.Join(state, "logins.json"))
	if err != nil {
		t.Fatal(err)
	}
	if two := kept.Dict("acme").Dict("two"); two.Str("email") != "two@acme.test" || two.Get("ends") != nil || two.Get("plan") != nil || !two.Has("checked_at") {
		t.Fatalf("the login made again: %s", run.Line(two))
	}
	if usual := kept.Dict("acme").Dict("default"); run.Line(usual) != `{"email": "owner@acme.test"}` {
		t.Fatalf("the login that answered nothing: %s", run.Line(usual))
	}
}
