package googlecloud

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// The meter is read as the tick left it, and an amount it cannot vouch for is never shown.
func TestTheSummaryShowsOnlyTheMonthsReadableSpend(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	write := func(name, text string) {
		t.Helper()
		path := filepath.Join(home, ".agentkit", name)
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	now := time.Date(2026, 11, 4, 12, 0, 0, 0, time.UTC)
	write("clock", fmt.Sprint(now.Unix()))
	t.Setenv("AK_GOOGLE_CLOCK", filepath.Join(home, ".agentkit", "clock"))
	if got := Summary(true); got != "off" {
		t.Fatalf("unconfigured: %q", got)
	}
	ledger := fmt.Sprintf(`{"answered":%d,"spent":12.5,"machines":{"one":{"price":1,"until":4},"two":{"price":1,"until":4,"from":2}}}`, now.Unix())
	for _, each := range []struct{ active, ledger, counted, said string }{
		{"true", "{}", "on · spend unknown", "on · spend unknown"},
		{"true", ledger, "on · €12.50 of €100 this month · 1 machine up", "on · €12.50 of €100 this month"},
		{"false", ledger, "off · 2 machines going once idle", "off"},
		{"true", `{"answered":1,"spent":12.5,"machines":{}}`, "on · spend unknown", "on · spend unknown"},
		{"true", fmt.Sprintf(`{"answered":%d,"spent":-1,"machines":{}}`, now.Unix()), "on · spend unknown", "on · spend unknown"},
		{"true", fmt.Sprintf(`{"answered":%d,"spent":0,"machines":{"one":{}}}`, now.Unix()), "on · spend unknown", "on · spend unknown"},
	} {
		write("config.toml", "[google_cloud]\nactive = "+each.active+"\nmax_month = 100\n")
		write("state/google-cloud-ledger.json", each.ledger)
		if got := Summary(true); got != each.counted {
			t.Errorf("counted %s: %q, want %q", each.ledger, got, each.counted)
		}
		if got := Summary(false); got != each.said {
			t.Errorf("%s: %q, want %q", each.ledger, got, each.said)
		}
	}
}
