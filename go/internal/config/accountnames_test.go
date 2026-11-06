package config

import "testing"

func TestAnAccountReadsAsItsPlaceAmongSeveral(t *testing.T) {
	listed := []string{"default", "shoal", "reef", "kelp"}
	for account, want := range map[string]string{"default": "Acme I", "kelp": "Acme IV", "gone": "Acme gone", "": "Acme"} {
		if got := AccountLabel(listed, account, "Acme"); got != want {
			t.Errorf("%q reads %q, not %q", account, got, want)
		}
	}
	if got := AccountLabel([]string{"shoal"}, "shoal", "Acme"); got != "Acme" {
		t.Errorf("one account reads %q", got)
	}
}
